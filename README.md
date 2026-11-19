# Ongelooflijk Archief

An unofficial, searchable archive of **De Ongelooflijke Podcast** (EO / NPO Radio 1). The project aims to be an IMDb-style reference for the show: every episode, guest, theme, mentioned person, book, and Bible reference — backed by real transcripts and LLM-extracted metadata rather than keyword heuristics.

**Open locally:** `site/dist/index.html` — a single self-contained file, no server needed.

## Project idea

De Ongelooflijke Podcast has been running since 2019. With 329+ episodes, it has become a substantial archive of conversations about faith, culture, philosophy, politics, and much more. The goal of this project is to make that archive navigable: search by guest, theme, or topic; explore who talks about what; read along with the transcript; look up where a Bible verse or a philosopher's name appeared.

The data pipeline has three phases:

1. **Feed** — parse the NPO RSS feed into per-episode snapshots (`data/feed/{n}.json`)
2. **Transcription** — upload each episode's MP3 to Azure MAI-Transcribe-2 with speaker diarization; store the result as `data/transcripts/{n}.json`; delete the MP3 afterwards
3. **Analysis** — send transcript + description to Claude (`claude-haiku-5-5`) to extract themes, people, books, Bible references (only actual citations), places, and a summary; store as `data/analysis/{n}.json`

A final build step compiles everything into `data/episodes.json` and inlines it into the single-page app.

## Repository layout

```
design-system/          Brand: tokens.json (source), tokens.css (generated), README.md (brand book), logos
site/src/               index.template.html — the whole app (HTML + CSS + JS inline)
site/dist/index.html    Built, self-contained page
data/
  raw/feed.xml          Snapshot of the NPO RSS feed
  feed/{n}.json         Per-episode feed snapshots (re-writable as feed changes)
  transcripts/{n}.json  Per-episode transcripts (Azure MAI-Transcribe-2 output)
  analysis/{n}.json     Per-episode LLM analysis (themes, people, books, etc.)
  speaker-corrections/  Manual speaker-ID overrides for each episode
  persons/{slug}.json   Per-person social-media links (hosts auto-extracted; guests manual)
  persons/images/       Profile photos ({slug}.jpg/png/webp)
  bible/{BOOK}.json     NBV21 verse text keyed by chapter and verse (scraped)
  word_index.json       Transcript-derived word frequencies per episode (9_build_word_index.py)
  voice-profiles/       Voice embeddings (.npy) used for speaker identification
  themes.json           18 fixed themes used across the archive
  episodes.json         Compiled episode data embedded in the site
  intermediate/         Scratch output of earlier build steps
scripts/
  1_parse_feed.py            Parse RSS feed → data/intermediate/raw.json + data/feed/
  2_extract_guests.py        Auto-extract guests from titles/descriptions
  3_build_episode_data.py    Compile episodes.json (themes, formats, quotes, bios)
  4_split_data.py            Split large data for the site build
  5_build_site.py            Build site/dist/index.html
  6_extract_person_socials.py  Mine RSS boilerplate for host social links → data/persons/
  7_fetch_person_images.py   Fetch profile photos via unavatar.io → data/persons/images/
  transcribe_azure.py        Transcribe episodes via Azure MAI-Transcribe-2
  analyze_episode.py         Analyse episodes with Claude (entity extraction → data/analysis/)
  8_enrich_people_wiki.py   Enrich people in analysis files with Wikipedia URLs and thumbnails
  9_build_word_index.py      Build transcript-derived word frequency index → data/word_index.json
  fix_speaker_counts.py      Remove excess Azure diarization speakers (dry-run or --apply)
  build_voice_profiles.py    Build Resemblyzer voice profiles from a known episode
  identify_speakers.py       Apply voice profiles to re-identify speakers in a transcript
  bootstrap_profiles.py      Iteratively bootstrap voice profiles across all transcribed episodes
  scrape_nbv21.py            Scrape NBV21 Bible verse text → data/bible/ (requires Playwright)
docs/
  transcript-schema.md  Transcript data contract (shape of transcripts/{n}.json)
  features.md           Feature inventory and design notes
CLAUDE.md               Design and coding guide for this project
```

## Local setup

**Prerequisites:** Python 3.12+, Git.

```bash
git clone <this-repo>
cd deongelooflijke

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
```

Create a `.env` file in the project root with your credentials:

```
AZURE_SPEECH_KEY=...
AZURE_SPEECH_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
ANTHROPIC_API_KEY=...
```

To view the site locally, use Python's built-in HTTP server (opening the file directly via `file://` will cause CORS policy errors on Windows):

```bash
python -m http.server 8000 --directory site/dist
```

Then open `http://localhost:8000` in your browser.

To rebuild the site from source after data changes:

```bash
python scripts/4_split_data.py && python scripts/5_build_site.py
# If data/word_index.json is present it is included automatically.
```

### Voice-based speaker identification (optional)

After installing the venv, you can build voice profiles for David and Stefan so future transcriptions are identified automatically:

```bash
# Build profiles from a correctly identified episode (327 is verified)
python scripts/build_voice_profiles.py --episode 327

# Check identification quality (dry-run)
python scripts/identify_speakers.py --episode 327 --dry-run

# Apply to any episode
python scripts/identify_speakers.py --episode 42 --apply
```

To scale up, `bootstrap_profiles.py` iterates through all transcribed episodes and identifies speakers by elimination (when exactly one speaker per episode lacks a profile), writing corrections and new profiles each round:

```bash
python scripts/bootstrap_profiles.py              # preview plan (dry-run)
python scripts/bootstrap_profiles.py --apply      # download audio, run Resemblyzer, write profiles
python scripts/bootstrap_profiles.py --apply --max-rounds 3
```

Requires `resemblyzer`, `librosa`, and `webrtcvad-wheels`. Profiles are stored in `data/voice-profiles/` as `.npy` files. Pass `--identify` to `transcribe_azure.py` to run identification automatically right after transcription.

### Fix over-segmented transcripts (optional)

Azure's diarization occasionally assigns more speaker tracks than participants. `fix_speaker_counts.py` strips the excess and reassigns their segments to the nearest preceding valid speaker:

```bash
python scripts/fix_speaker_counts.py               # dry-run: report only
python scripts/fix_speaker_counts.py --apply       # write corrected files
python scripts/fix_speaker_counts.py --episode 42 --apply
```

## Transcript format

Each `data/transcripts/{n}.json` follows the schema in `docs/transcript-schema.md`:

```json
{
  "episode": 327,
  "source": { "audio": "...", "model": "azure/mai-transcribe-2", "created": "..." },
  "speakers": [{ "id": "S1", "name": "David Boogerd", "role": "host" }, ...],
  "segments": [{ "start": 0.0, "end": 3.2, "speaker": "S1", "text": "..." }, ...],
  "events": [],
  "summary": { "tldr": "...", "points": [] },
  "chapters": [], "highlights": [], "mentions": [], "bible": []
}
```

Speaker IDs are assigned by word-count rank: highest → David Boogerd, second (when Stefan Paas is present) → Stefan Paas, rest → guests in order. Manual corrections go in `data/speaker-corrections/{n}.json`.

## Analysis format

Each `data/analysis/{n}.json` contains LLM-extracted fields:

```json
{
  "episode": 327,
  "analyzed": "2026-11-11",
  "model": "claude-haiku-5-5",
  "themes": ["Bijbel & Jezus", "God & geloof"],
  "guests": ["Kader Abdolah"],
  "people": [{ "name": "Karl Marx", "note": "filosoof", "start_seconds": 754,
               "wiki_url": "https://nl.wikipedia.org/wiki/Karl_Marx",
               "wiki_image": "https://upload.wikimedia.org/…/100px-Marx.jpg",
               "wiki_lang": "nl", "wiki_pageid": 12345, "wiki_checked": true }],
  "books": [{ "title": "Jezus", "author": "Kader Abdolah", "note": "..." }],
  "bible_refs": [{ "ref": "Johannes 3:16", "note": "..." }],
  "places": ["Iran", "Nederland"],
  "summary_tldr": "...",
  "quotes": ["..."]
}
```

`bible_refs` only includes actual citations (a specific verse or chapter quoted or directly referenced), never a general mention of the Bible.

`people[].start_seconds` is the transcript timestamp (in seconds) when the person is first mentioned. `wiki_*` fields are added by `8_enrich_people_wiki.py` after the initial analysis. `wiki_checked: true` marks a person as processed regardless of whether a match was found; `wiki_pageid` is stored even when `wiki_url` is absent (a pageinfo failure), so a re-run can retry without a new LLM call.

## Pipeline

### 1. Parse the feed

Download the RSS feed and save it as `data/raw/feed.xml`, then:

```bash
python scripts/1_parse_feed.py          # → data/intermediate/raw.json + data/feed/
python scripts/2_extract_guests.py      # → data/intermediate/eps1.json
python scripts/3_build_episode_data.py  # → data/episodes.json
```

### 2. Transcribe episodes (requires Azure)

Requires `AZURE_SPEECH_KEY` and `AZURE_SPEECH_ENDPOINT` in `.env` (or environment):

```bash
python scripts/transcribe_azure.py --all-missing --delete-mp3
# Or a single episode:
python scripts/transcribe_azure.py --episode 42 --delete-mp3
```

MP3s are downloaded on demand from the NPO feed URL and deleted after a successful transcription. Speaker corrections can be placed in `data/speaker-corrections/{n}.json` as `{"1": "Name", "2": "Name"}`.

### 3. Analyse episodes (requires Anthropic API)

Requires `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` in `.env` (or environment):

```bash
python scripts/analyze_episode.py --all-missing
# Or a single episode:
python scripts/analyze_episode.py --episode 42
# Re-analyse with a different model:
python scripts/analyze_episode.py --all-missing --model claude-sonnet-5-5
```

Prompt caching is used on the system prompt, so running all episodes in one pass is cheap (~$0.005 per episode at Haiku 5.5 rates).

### 4. Enrich people with Wikipedia (optional)

For each person extracted by `analyze_episode.py`, this script searches Wikipedia (Dutch first, then English), runs one batched LLM call to verify the best match against the episode context, and stores the page URL and thumbnail in `data/analysis/{n}.json`.

No API key is required. Wikipedia allows up to 200 requests/min for bots with a descriptive User-Agent; the script uses a 1-second delay between requests and exponential backoff on 429 responses.

```bash
python scripts/8_enrich_people_wiki.py --all-missing
# Or a single episode:
python scripts/8_enrich_people_wiki.py --episode 42
# Re-check even already-processed people:
python scripts/8_enrich_people_wiki.py --episode 42 --force
```

Re-running without `--force` is safe and useful: it retries any person where the Wikipedia match was found but the pageinfo call failed (stored as `wiki_pageid` without `wiki_url`), without re-running the LLM verification step.

### 5. Person socials and images (optional)

Extract social-media links for David Boogerd and Stefan Paas from the RSS boilerplate, and fetch their profile photos:

```bash
python scripts/6_extract_person_socials.py         # → data/persons/{slug}.json
python scripts/7_fetch_person_images.py            # → data/persons/images/{slug}.jpg
```

Guest profiles must be added manually: create `data/persons/{slug}.json` with a `socials` key. For LinkedIn photos (not covered by unavatar.io), drop the image into `data/persons/images/{slug}.jpg` by hand.

### 6. Bible verse text (optional)

Scrape the full NBV21 text for use in transcript Bible-reference lookups. Requires Playwright:

```bash
pip install playwright requests
playwright install chromium
python scripts/scrape_nbv21.py                     # → data/bible/{BOOK}.json
```

The script is resumable — chapters already on disk are skipped.

### 7. Build the word index (optional but recommended)

Extracts NOUN and PROPN tokens from every transcript using spaCy's Dutch model,
lemmatizes them, and writes per-episode word-frequency data to `data/word_index.json`.
The site's *Meest gebruikte woorden* chart on Statistieken uses this instead of the
coarser title/description counts when the file is present.

Requires spaCy and the Dutch model (one-time download, ~13 MB):

```bash
pip install spacy
python -m spacy download nl_core_news_sm

python scripts/9_build_word_index.py --dry-run  # preview first transcript
python scripts/9_build_word_index.py            # full run (~10–20 min for 329 episodes)
```

The script is incremental: re-running after new transcriptions only processes episodes
not yet in the index. Use `--rebuild` to reprocess everything.

### 8. Build the site

```bash
python scripts/4_split_data.py && python scripts/5_build_site.py
# → site/dist/index.html
# (also copies data/word_index.json to site/dist/data/ if present)
```

## Design

The visual language is documented in `design-system/README.md` and encoded as CSS custom properties in `design-system/tokens.css`. In brief: classical serif (Lora + Spectral) on warm parchment, dark-brown ink, gold data marks, and EO violet for interactive elements — old engraving meets modern listening.

## Sources

- RSS feed: https://podcast.npo.nl/feed/de-ongelooflijke-podcast.xml
- NPO Radio 1: https://www.nporadio1.nl/podcasts/de-ongelooflijke-podcast

The artwork and EO wordmark belong to EO / De Ongelooflijke. This is an unofficial fan archive.
