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
  themes.json           18 fixed themes used across the archive
  episodes.json         Compiled episode data embedded in the site
  intermediate/         Scratch output of earlier build steps
scripts/
  1_parse_feed.py       Parse RSS feed → data/intermediate/raw.json + data/feed/
  2_extract_guests.py   Auto-extract guests from titles/descriptions
  3_build_episode_data.py  Compile episodes.json (themes, formats, quotes, bios)
  4_split_data.py       Split large data for the site build
  5_build_site.py       Build site/dist/index.html
  transcribe_azure.py   Transcribe episodes via Azure MAI-Transcribe-2
  analyze_episode.py    Analyse episodes with Claude (LLM entity extraction)
docs/
  transcript-schema.md  Transcript data contract (shape of transcripts/{n}.json)
  features.md           Feature inventory and design notes
CLAUDE.md               Design and coding guide for this project
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
  "people": [{ "name": "Karl Marx", "note": "filosoof" }],
  "books": [{ "title": "Jezus", "author": "Kader Abdolah", "note": "..." }],
  "bible_refs": [{ "ref": "Johannes 3:16", "note": "..." }],
  "places": ["Iran", "Nederland"],
  "summary_tldr": "...",
  "quotes": ["..."]
}
```

`bible_refs` only includes actual citations (a specific verse or chapter quoted or directly referenced), never a general mention of the Bible.

## Pipeline

### 1. Refresh the feed

Download the RSS feed and save it as `data/raw/feed.xml`, then:

```bash
python scripts/1_parse_feed.py          # → data/intermediate/raw.json + data/feed/
python scripts/2_extract_guests.py      # → data/intermediate/eps1.json
python scripts/3_build_episode_data.py  # → data/episodes.json
```

### 2. Transcribe episodes

Requires `AZURE_SPEECH_KEY` and `AZURE_SPEECH_ENDPOINT` in `.env` (or environment):

```bash
python scripts/transcribe_azure.py --all-missing --delete-mp3
# Or a single episode:
python scripts/transcribe_azure.py --episode 42 --delete-mp3
```

MP3s are downloaded on demand from the NPO feed URL and deleted after a successful transcription. Speaker corrections can be placed in `data/speaker-corrections/{n}.json` as `{"1": "Name", "2": "Name"}`.

### 3. Analyse episodes

Requires `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` in `.env` (or environment):

```bash
python scripts/analyze_episode.py --all-missing
# Or a single episode:
python scripts/analyze_episode.py --episode 42
# Re-analyse with a different model:
python scripts/analyze_episode.py --all-missing --model claude-sonnet-5-5
```

Prompt caching is used on the system prompt, so running all episodes in one pass is cheap (~$0.005 per episode at Haiku 5.5 rates).

### 4. Build the site

```bash
python scripts/4_split_data.py && python scripts/5_build_site.py
# → site/dist/index.html
```

## Design

The visual language is documented in `design-system/README.md` and encoded as CSS custom properties in `design-system/tokens.css`. In brief: classical serif (Lora + Spectral) on warm parchment, dark-brown ink, gold data marks, and EO violet for interactive elements — old engraving meets modern listening.

## Sources

- RSS feed: https://podcast.npo.nl/feed/de-ongelooflijke-podcast.xml
- NPO Radio 1: https://www.nporadio1.nl/podcasts/de-ongelooflijke-podcast

The artwork and EO wordmark belong to EO / De Ongelooflijke. This is an unofficial fan archive.
