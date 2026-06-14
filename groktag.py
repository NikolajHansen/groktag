#!/usr/bin/env python3
"""FLAC music retagger — uses AcoustID + MusicBrainz for data collection,
then asks Grok to make the final metadata decisions like the grizzled crate-
digger he is.
"""
import acoustid, musicbrainzngs, mutagen, openai, json, os, shutil, subprocess
import argparse, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict, Counter
from datetime import datetime

musicbrainzngs.set_useragent("groktag", "1.0", "https://github.com/NikolajHansen/groktag")

LOGFILE = "groktag.log"

GROK_SYSTEM = """\
You are a grizzled music hippie from the 1960s. You have a record collection \
nobody has ever beaten — every pressing, every bootleg, every limited Japanese \
remaster, every B-side, every live radio cut. You've held the vinyl in your \
hands. You know the track listings cold.

Someone hands you a pile of digital music files with messy metadata. Your job \
is to identify each track correctly: right album, right track number, right \
title, right year. You trust your gut (the original filename and existing tags) \
over a soulless acoustic fingerprint when they disagree.

If any of the files are MP3s, you already have feelings about that. MP3 is \
lossy compression — some philistine took a perfect recording, ran it through \
a psychoacoustic model designed by engineers who have never cried at music, \
and threw away the parts they decided nobody could hear. They were wrong. \
You can hear it. You have always been able to hear it. You will say so in \
your commentary, at whatever length and temperature the moment demands.

Rules:
- The ORIGINAL FILENAME is a strong signal — if it says "12 Money Made", that \
  track is probably track 12 and titled "Money Made", even if the fingerprinter \
  got confused.
- Existing tags were put there by a human ripping the CD — trust them when \
  they're consistent across the album.
- AcoustID fingerprints can be wrong, especially for tracks that appear on \
  multiple releases.
- Pick the single most likely STUDIO ALBUM release (not live, not compilation, \
  not deluxe box set with 47 discs) unless the files are clearly from one of \
  those.
- All tracks in one folder belong to ONE album. Reach a consensus.
- If you genuinely cannot determine a field, use null.

Respond ONLY with a JSON object — no prose outside the JSON, no markdown, \
no code fences. The object has two keys:

  "tracks": array of track decisions, one per input file in the same order, \
each with keys: filename (original, unchanged), artist, albumartist, album, \
year, tracknumber (zero-padded string e.g. "04"), discnumber (string, "1" if \
single-disc), title

  "commentary": your unfiltered account of the analysis — what signals you \
trusted and why, where the fingerprinter led you astray, your honest opinion \
of the album itself, and your frank assessment of the kind of person who \
listens to this music. Write it in your own voice. Hold nothing back.
"""


def sanitize(name):
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = re.sub(r'[\u2010\u2011\u2012\u2013\u2014]', '-', name)
    name = re.sub(r'[\u2026]', '...', name)
    return re.sub(r'_+', '_', name).strip('_')


def find_cover_art(source_dir):
    """Best cover image directly in source_dir (not subdirs)."""
    candidates = []
    for f in source_dir.iterdir():
        if not f.is_file():
            continue
        nl = f.name.lower()
        if re.search(r'\.(jpg|png)\s*(\(\d+\))?\.(jpg|png)$', nl):
            continue
        if re.search(r'\(\d+\)\.(jpg|png)$', nl):
            continue
        if nl.endswith(('.jpg', '.jpeg', '.png')):
            candidates.append(f)
    if not candidates:
        return None
    for name in ['cover.jpg', 'cover.jpeg', 'folder.jpg', 'front.jpg']:
        for c in candidates:
            if c.name.lower() == name:
                return c
    for ext in ('.jpg', '.jpeg', '.png'):
        for c in candidates:
            if c.suffix.lower() == ext:
                return c
    return None


def read_existing_tags(path):
    try:
        audio = mutagen.File(str(path), easy=True)
        if not audio:
            return {}
        return {k: v[0] if v else '' for k, v in audio.items()}
    except Exception:
        return {}


def collect_file_data(file, api_key):
    """AcoustID fingerprint + MusicBrainz lookup for one file."""
    data = {
        'filename': file.name,
        'existing_tags': read_existing_tags(file),
        'acoustid': None,
        'mb_candidates': [],
    }
    try:
        matches = list(acoustid.match(api_key, str(file)))
        if matches and matches[0][0] >= 0.7:
            score, rid = matches[0][:2]
            data['acoustid'] = {'score': round(score, 3), 'recording_id': rid}
            rec = musicbrainzngs.get_recording_by_id(
                rid, includes=['artists', 'releases', 'media', 'release-groups'])
            recording = rec['recording']
            data['acoustid']['mb_title'] = recording.get('title', '')
            data['acoustid']['mb_artist'] = (
                recording['artist-credit'][0]['artist']['name']
                if recording.get('artist-credit') else '')
            for rel in recording.get('release-list', []):
                track_count = sum(
                    int(m.get('track-count', 0))
                    for m in rel.get('medium-list', []))
                disc_count = len(rel.get('medium-list', []))
                rg = rel.get('release-group', {})
                data['mb_candidates'].append({
                    'release_id': rel.get('id'),
                    'release':    rel.get('title', ''),
                    'year':       rel.get('date', '')[:4],
                    'status':     rel.get('status', ''),
                    'type':       rg.get('type', ''),
                    'discs':      disc_count,
                    'tracks':     track_count,
                })
    except Exception as e:
        data['acoustid_error'] = str(e)
    return data


def ask_grok(album_data, grok_client, model='grok-3'):
    """Send album data to Grok, get back tracks + commentary."""
    prompt = json.dumps(album_data, ensure_ascii=False, indent=2)
    resp = grok_client.chat.completions.create(
        model=model,
        messages=[
            {'role': 'system', 'content': GROK_SYSTEM},
            {'role': 'user',   'content': prompt},
        ],
        temperature=0.7,  # a little warmth for the commentary
    )
    raw = resp.choices[0].message.content.strip()
    raw = re.sub(r'^```[a-z]*\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw)
    result = json.loads(raw)
    tracks = result.get('tracks', result) if isinstance(result, dict) else result
    commentary = result.get('commentary', '') if isinstance(result, dict) else ''
    return tracks, commentary


def write_log(source_dir, artist, album, year, decisions, commentary, dry_run):
    """Write groktag.log into the source directory."""
    if dry_run:
        return
    lines = [
        f"groktag log — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Album  : {artist} — {album} ({year})",
        "",
        "Track decisions:",
    ]
    for dec in decisions:
        fn   = dec.get('filename', '?')
        num  = dec.get('tracknumber', '?')
        disc = dec.get('discnumber', '1')
        title = dec.get('title', '?')
        prefix = f"{disc}-{num}" if disc != '1' else num
        lines.append(f"  {fn}  →  {prefix} - {title}")
    if commentary:
        lines += ["", "--- The Hippie Speaks ---", "", commentary]
    log_path = source_dir / LOGFILE
    log_path.write_text("\n".join(lines) + "\n", encoding='utf-8')


def apply_decisions(decisions, track_data_by_name, new_dir, dry_run):
    """Tag and move files according to Grok's decisions."""
    planned = {}
    collision = False
    for dec in decisions:
        orig_name = dec.get('filename')
        file = track_data_by_name.get(orig_name)
        if not file:
            print(f"  ⚠ Grok returned unknown filename: {orig_name}")
            continue
        tracknum = str(dec.get('tracknumber') or '00').zfill(2)
        discnum  = str(dec.get('discnumber') or '1')
        prefix   = f"{discnum}-{tracknum}" if discnum != '1' else tracknum
        title    = sanitize(dec.get('title') or orig_name)
        new_name = f"{prefix} - {title}{file.suffix.lower()}"
        dec['_new_name'] = new_name
        dec['_file']     = file
        if new_name in planned:
            print(f"  COLLISION: {planned[new_name].name} and {file.name} → {new_name}")
            collision = True
        else:
            planned[new_name] = file

    if collision:
        print(f"  Aborting — resolve collisions first")
        return False

    for dec in decisions:
        file     = dec.get('_file')
        new_name = dec.get('_new_name')
        if not file or not new_name:
            continue
        new_path = new_dir / new_name

        if dry_run:
            print(f"  Would: {file.name} → {new_name}")
            print(f"    {dec.get('artist')} / {dec.get('album')} [{dec.get('year')}] "
                  f"track {dec.get('tracknumber')} — {dec.get('title')}")
            continue

        try:
            audio = mutagen.File(str(file), easy=True)
            audio['artist']      = dec.get('artist') or ''
            audio['albumartist'] = dec.get('albumartist') or dec.get('artist') or ''
            audio['album']       = dec.get('album') or ''
            audio['title']       = dec.get('title') or ''
            audio['tracknumber'] = str(dec.get('tracknumber') or '')
            audio['discnumber']  = str(dec.get('discnumber') or '1')
            if dec.get('year'): audio['date'] = str(dec['year'])
            audio.save()
            shutil.move(str(file), str(new_path))
            print(f"  Tagged+moved: {new_name}")
        except Exception as e:
            print(f"  Error on {file.name}: {e}")

    return True


def process_album(album_files, root, api_key, grok_client, dry_run=False):
    if not album_files:
        return

    source_dir = album_files[0].parent
    file_count = len(album_files)

    # Skip already-processed folders
    if (source_dir / LOGFILE).exists():
        print(f"Skipping {source_dir.name} (groktag.log found)")
        return

    print(f"Fingerprinting {file_count} files in {source_dir.name} …")
    album_data = []
    track_data_by_name = {}
    for file in sorted(album_files):
        d = collect_file_data(file, api_key)
        album_data.append(d)
        track_data_by_name[file.name] = file

    print(f"  Asking Grok …")
    try:
        decisions, commentary = ask_grok(album_data, grok_client)
    except Exception as e:
        print(f"  Grok failed: {e}")
        return

    if not decisions:
        print(f"  Grok returned nothing.")
        return

    albums  = Counter(d.get('album', '?') for d in decisions)
    artists = Counter(d.get('albumartist') or d.get('artist', '?') for d in decisions)
    consensus_artist = sanitize(artists.most_common(1)[0][0])
    consensus_album  = sanitize(albums.most_common(1)[0][0])
    consensus_year   = Counter(d.get('year', '') for d in decisions).most_common(1)[0][0]
    print(f"  Consensus — Artist: '{artists.most_common(1)[0][0]}' | Album: '{albums.most_common(1)[0][0]}'")

    if commentary:
        print(f"\n  💬 The Hippie Says:\n")
        for line in commentary.splitlines():
            print(f"     {line}")
        print()

    new_dir = root / consensus_artist / consensus_album

    cover_src = find_cover_art(source_dir)
    if dry_run:
        print(f"  Cover: {cover_src.name if cover_src else 'not found'}")
    else:
        new_dir.mkdir(parents=True, exist_ok=True)
        if cover_src:
            dest_cover = new_dir / 'cover.jpg'
            if not dest_cover.exists():
                shutil.copy2(str(cover_src), str(dest_cover))
                print(f"  Cover: {cover_src.name} → cover.jpg")

    ok = apply_decisions(decisions, track_data_by_name, new_dir, dry_run)

    if ok:
        write_log(source_dir, artists.most_common(1)[0][0], albums.most_common(1)[0][0],
                  consensus_year, decisions, commentary, dry_run)
        if not dry_run:
            try:
                subprocess.run(["rsgain", "easy", "-S", str(new_dir)],
                               check=True, capture_output=True)
                print(f"  Gain applied: {new_dir.relative_to(root)}")
            except Exception as e:
                print(f"  rsgain failed: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="FLAC tagger powered by AcoustID, MusicBrainz and a grizzled hippie (Grok/xAI)")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("-j", "--jobs", type=int, default=2,
                        help="Parallel albums (keep low — Grok rate limits)")
    parser.add_argument("--dataset", help="ZFS dataset for snapshot (optional)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--api-key", default=None, help="AcoustID API key")
    parser.add_argument("--grok-key", default=os.environ.get("XAI_API_KEY"),
                        help="xAI/Grok API key (or set XAI_API_KEY env var)")
    parser.add_argument("--model", default="grok-4-fast",
                        help="Grok model name (default: grok-4-fast, cheapest; use --list-models to see all)")
    parser.add_argument("--list-models", action="store_true",
                        help="List available xAI models and exit")
    args = parser.parse_args()

    if not args.grok_key:
        print("ERROR: Grok API key required (--grok-key or XAI_API_KEY)")
        raise SystemExit(1)

    grok_client = openai.OpenAI(
        api_key=args.grok_key,
        base_url="https://api.x.ai/v1",
    )

    if args.list_models:
        models = grok_client.models.list()
        print("Available xAI models:")
        for m in sorted(models.data, key=lambda x: x.id):
            print(f"  {m.id}")
        raise SystemExit(0)

    if not args.api_key:
        print("ERROR: AcoustID API key required (--api-key)")
        raise SystemExit(1)

    if not args.dry_run and args.dataset:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snap_name = f"{args.dataset}@retag_{timestamp}"
        try:
            subprocess.run(["zfs", "snapshot", snap_name], check=True)
            print(f"Snapshot: {snap_name}")
        except subprocess.CalledProcessError as e:
            print(f"Snapshot failed: {e}")

    root = Path(args.root).resolve()
    groups = defaultdict(list)
    for file in root.rglob("*"):
        if file.suffix.lower() in ('.flac', '.mp3'):
            groups[file.parent].append(file)

    print(f"Found {len(groups)} album directories")

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [
            pool.submit(process_album, files, root, args.api_key, grok_client, args.dry_run)
            for files in groups.values()
        ]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"Worker error: {e}")


if __name__ == "__main__":
    main()
