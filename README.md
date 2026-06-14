# groktag

**AI-powered FLAC music tagger using acoustic fingerprinting and a grizzled hippie.**

---

## Concept

Most music taggers work by acoustic fingerprinting a file, finding a match in a database, and
applying whatever metadata comes back. This works well when the fingerprint is unambiguous —
but real-world collections are messy. Tracks appear on studio albums, live albums, compilations,
deluxe box sets, and region-specific pressings. A fingerprinter that matched "Money Made" to
a live album and tagged it track 00 is not wrong in a narrow sense — but it is wrong in any
sense that matters.

groktag takes a different approach. It uses fingerprinting and MusicBrainz **only as a data
collection layer**. All the actual decisions — which release is the right one, what the track
number is, what to trust when signals disagree — are delegated to a large language model
(Grok, from xAI) that reasons about the entire album as a unit.

The key insight is that an LLM can weigh contradictory signals the same way a knowledgeable
human would: the original filename says track 12, the existing ripped tags say "Money Made",
the fingerprinter got confused by a live version — the answer is obviously track 12, "Money Made",
from the studio album. No algorithm encodes that judgment cleanly. A language model does.

---

## The Hippie

Grok is not asked to be a neutral metadata service. It is given a personality:

> *You were at Berkeley, California when the Free Speech Movement wrote the rules for what real
> liberalism looks like. You were in San Francisco for the Summer of Love. You watched the moon
> landing live on a black-and-white TV in 1969, and you happened to know a couple of the gaffers
> and the boom operator that Stanley Kubrick worked with — draw your own conclusions.*

> *You have absolutely no patience for the sanitised, focus-grouped, corporate-approved version
> of progressive politics that passes for radicalism today. A true liberal believes in free thought,
> free speech, and free music. You will say so when the mood strikes.*

> *You have a record collection nobody has ever beaten. You've held every pressing in your hands.
> You know the track listings cold. And if someone hands you an MP3, you are going to have words.*

The hippie is told to:

- Trust the **original filename** as a strong signal — someone named that file for a reason
- Trust **existing ripped tags** when they're consistent across the album — a human put them there
- Treat acoustic fingerprints as **supporting evidence**, not gospel
- Prefer the **original studio album** over live albums, compilations, and deluxe box sets
- Reason across **all tracks in the folder together** — they belong to one album
- Have and express opinions on the music, the listener, lossy compression, and anything else that comes to mind

After making his decisions, the hippie writes a `groktag.log` in the source folder. This log
contains the track mapping and — more importantly — his **unfiltered commentary**: what signals
he trusted, where the fingerprinter was wrong, his honest opinion of the album, and his frank
assessment of the kind of person who listens to this music. He holds nothing back.

---

## Algorithm

```
For each album directory (all .flac files in the same folder = one album):

  1. FINGERPRINT
     AcoustID acoustic fingerprinting → MusicBrainz recording ID + confidence score

  2. COLLECT
     Per file, fetch from MusicBrainz:
       - Recording title and artist
       - All candidate releases (title, year, status, release-group type, disc count, track count)
       - Existing file tags (read with mutagen)
       - Original filename

  3. BUNDLE
     Assemble all per-file data for the album into a single JSON payload

  4. ASK THE HIPPIE
     Send the JSON to Grok with the grizzled hippie system prompt.
     Grok returns a JSON array — one entry per file — with:
       artist, albumartist, album, year, tracknumber, discnumber, title

  5. COLLISION CHECK
     Before touching any file, verify no two tracks would land on the same filename.
     Abort the album if collisions are found.

  6. APPLY
     For each file:
       - Write tags with mutagen (artist, albumartist, album, title, tracknumber, discnumber, date)
       - Rename and move to: <root>/<Artist>/<Album>/<tracknumber> - <Title>.flac
         Multi-disc prefix: <disc>-<track> - <Title>.flac

  7. COVER ART
     Find the best cover image in the source folder (priority: cover.jpg > folder.jpg > any jpg/png).
     Skip duplicates (folder.jpg.jpg, numbered copies).
     Copy to <Artist>/<Album>/cover.jpg.

  8. REPLAYGAIN
     Run rsgain on the completed album directory.

  9. LOG
     Write groktag.log into the source folder containing: the track mapping,
     and the hippie's unfiltered commentary on the album and its listeners.
     On subsequent runs, any folder containing groktag.log is skipped entirely.
```

One Grok API call is made per album directory. The model sees all tracks together, which allows
cross-track reasoning: if 13 of 15 fingerprints agree on "Back in Black", the remaining 2 are
almost certainly also "Back in Black" even if their fingerprints are confused.

---

## Requirements

- Python 3.10+
- [fpcalc](https://acoustid.org/chromaprint) (Chromaprint) — must be on `PATH`
- [rsgain](https://github.com/complexlogic/rsgain) — for ReplayGain (optional but recommended)
- An [AcoustID API key](https://acoustid.org/login) (free)
- An [xAI API key](https://console.x.ai/) for Grok

---

## Installation

### FreeBSD

```sh
pkg install chromaprint rsgain py311-acoustid py311-musicbrainzngs py311-mutagen py311-openai
git clone https://github.com/NikolajHansen/groktag.git
cp groktag/groktag.py ~/bin/groktag
chmod +x ~/bin/groktag
```

### Linux (Debian/Ubuntu)

```sh
sudo apt install chromaprint-tools rsgain python3-pip
pip install pyacoustid musicbrainzngs mutagen openai
git clone https://github.com/NikolajHansen/groktag.git
sudo cp groktag/groktag.py /usr/local/bin/groktag
sudo chmod +x /usr/local/bin/groktag
```

> `rsgain` may not be in apt on older distros — build from source or grab a release binary from
> [github.com/complexlogic/rsgain](https://github.com/complexlogic/rsgain/releases).

### Linux (Arch)

```sh
sudo pacman -S chromaprint rsgain python-pip
pip install pyacoustid musicbrainzngs mutagen openai
git clone https://github.com/NikolajHansen/groktag.git
sudo cp groktag/groktag.py /usr/local/bin/groktag
sudo chmod +x /usr/local/bin/groktag
```

### macOS

```sh
brew install chromaprint rsgain python
pip3 install pyacoustid musicbrainzngs mutagen openai
git clone https://github.com/NikolajHansen/groktag.git
cp groktag/groktag.py ~/bin/groktag
chmod +x ~/bin/groktag
```

### Windows

1. Install [Python 3.10+](https://www.python.org/downloads/windows/) — tick **Add to PATH**
2. Install [Chromaprint](https://acoustid.org/chromaprint) — extract `fpcalc.exe`, put it somewhere on your `PATH` (e.g. `C:\Windows\System32`)
3. Install [rsgain](https://github.com/complexlogic/rsgain/releases) — grab the Windows release, add to `PATH`
4. Open a command prompt:

```bat
pip install pyacoustid musicbrainzngs mutagen openai
git clone https://github.com/NikolajHansen/groktag.git
```

5. Run groktag directly with Python:

```bat
set XAI_API_KEY=your_xai_key
python groktag\groktag.py C:\Music --api-key your_acoustid_key --dry-run
```

> The hippie has strong opinions about people who store lossless audio on Windows. He will share them.

---

## Usage

```sh
# Dry run — shows what would happen, touches nothing
XAI_API_KEY=your_xai_key groktag /path/to/music \
  --api-key your_acoustid_key \
  --dry-run

# Live run with ZFS snapshot before starting
XAI_API_KEY=your_xai_key groktag /path/to/music \
  --api-key your_acoustid_key \
  --dataset zpool/music

# Options
groktag [root]                    # default: current directory
  --api-key KEY                   # AcoustID API key (required)
  --grok-key KEY                  # xAI key (or set XAI_API_KEY env var)
  --model grok-4-fast             # Grok model (default: grok-4-fast — cheapest; use --list-models)
  --list-models                   # List available xAI models and exit
  -j, --jobs N                    # Parallel albums (default: 2; keep low for rate limits)
  --dataset POOL/DATASET          # ZFS dataset to snapshot before run
  --dry-run                       # Preview only, no changes
```

### Output structure

```
<root>/
  AC_DC/
    Back in Black/
      01 - Hells Bells.flac
      02 - Shoot to Thrill.flac
      ...
      cover.jpg
    Highway to Hell/
      ...
  Metallica/
    Hardwired... to Self-Destruct/
      1-01 - Hardwired.flac
      ...
      2-01 - Confusion.flac
      ...
```

---

## Cost Warning

> **groktag makes one Grok API call per album directory.** On a large collection this adds up.

Each album sends roughly 5–30KB of JSON (filenames, existing tags, AcoustID results, MusicBrainz
candidates for every track) and receives a few KB of JSON back plus the hippie's commentary.
A rough estimate for `grok-3`:

| Collection size | Albums | Approx. input tokens | Approx. cost |
|---|---|---|---|
| Small (50 albums) | 50 | ~500K | ~$1–2 |
| Medium (500 albums) | 500 | ~5M | ~$10–20 |
| Large (5000 albums) | 5000 | ~50M | ~$100–200 |

These are rough estimates — actual cost depends on album size, MusicBrainz result depth, and
commentary length. The `groktag.log` skip mechanism means **you only pay once per album** — 
re-runs on already-processed folders cost nothing.

**Check current xAI pricing before running on a large collection:**
👉 [x.ai/api](https://x.ai/api#pricing)

To minimise cost:
- Always do a `--dry-run` first to catch problems before committing API calls
- Use `-j 1` or `-j 2` to avoid hammering the API
- The `--model grok-3-mini` (if available) may be cheaper for straightforward collections

---

## Automated / Cron Usage

Because groktag skips already-processed folders (`groktag.log`), it is safe to point at a
watched music drop folder and run on a schedule — it will only process genuinely new albums.

### Linux / macOS / FreeBSD (cron)

Add to crontab with `crontab -e`:

```cron
# Run groktag every night at 02:00 on new albums in /music/inbox
0 2 * * * XAI_API_KEY=your_xai_key /usr/local/bin/groktag /music/inbox \
  --api-key your_acoustid_key -j 2 >> /var/log/groktag.log 2>&1
```

Or as a dedicated cron file in `/etc/cron.d/groktag`:

```
0 2 * * * youruser XAI_API_KEY=your_xai_key /usr/local/bin/groktag /music/inbox \
  --api-key your_acoustid_key -j 2 >> /var/log/groktag.log 2>&1
```

### FreeBSD (periodic)

Add to `/etc/periodic.conf`:

```sh
daily_local="/usr/local/etc/periodic/daily/groktag"
```

Create `/usr/local/etc/periodic/daily/groktag`:

```sh
#!/bin/sh
export XAI_API_KEY=your_xai_key
/usr/local/bin/groktag /greenlake/media/music/inbox \
  --api-key your_acoustid_key \
  --dataset greenlake/media \
  -j 2
```

```sh
chmod +x /usr/local/etc/periodic/daily/groktag
```

### Windows (Task Scheduler)

Create a batch file `groktag_run.bat`:

```bat
@echo off
set XAI_API_KEY=your_xai_key
python C:\path\to\groktag.py C:\Music\Inbox --api-key your_acoustid_key -j 2 >> C:\Logs\groktag.log 2>&1
```

In Task Scheduler: create a basic task, trigger Daily, action = run `groktag_run.bat`.

> Store your API keys in environment variables or a secrets manager — never hardcode them in
> scripts that might end up in version control.

- Parallelism is limited by Grok API rate limits. `-j 2` is a safe default.
- Albums where collision detection fails are skipped with a message — fix them manually and re-run.
- groktag is idempotent: re-running on already-tagged files is safe (cover art won't be overwritten).
- Each processed source folder receives a `groktag.log` file. On re-run, folders containing this file are skipped automatically — no re-fingerprinting, no wasted API calls.
- The log contains the track mapping and the hippie's commentary. Read it for entertainment.
- AcoustID fingerprinting requires `fpcalc` on `PATH`. Install Chromaprint for your platform.

---

## License

GPL-3.0 — see [LICENSE](LICENSE).
