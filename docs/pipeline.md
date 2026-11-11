# Data pipeline

The pipeline has four numbered stages plus two on-demand steps. Run them in order when processing new episodes.

## Stage 1 — Feed parsing

```bash
python scripts/1_parse_feed.py
python scripts/2_extract_guests.py
python scripts/3_build_episode_data.py
```

**Input:** `data/raw/feed.xml` (download manually from the NPO RSS URL first)

**Output:**
- `data/intermediate/raw.json` — parsed feed items
- `data/intermediate/eps1.json` — with auto-extracted guests
- `data/feed/{n}.json` — per-episode feed snapshots (title, date, description, MP3 URL, NPO slug/ID)
- `data/episodes.json` — compiled master file with themes, formats, quotes, bios

`3_build_episode_data.py` applies keyword-based theme classification (18 themes), normalises guest names, and assigns episode formats (Gesprek, Interview, Duet, Trailer, Spin-off). It also inlines the `D.bios` lookup used on person pages.

**Data sources used by the site from `data/episodes.json`:**

| Field | Source |
|---|---|
| `n` | Episode number (null for unnumbered) |
| `t` | Title (without `#n – ` prefix) |
| `d` | ISO date string |
| `s` | Duration in seconds |
| `g` | Guest name array |
| `p` | Boolean — Stefan Paas present |
| `sj` | Subjects discussed (people names from title/description) |
| `th` | Theme labels array |
| `f` | Format string |
| `x` | Full description (not in inline index, fetched on demand) |
| `r` | Recommended episode numbers array |
| `id` / `sl` | NPO page ID and slug |
| `q` | Quotes array (from description) |
| `mp3` | MP3 URL |

## Stage 2 — Transcription

Requires `AZURE_SPEECH_KEY` and `AZURE_SPEECH_ENDPOINT` in `.env`.

```bash
python scripts/transcribe_azure.py --all-missing --delete-mp3
python scripts/transcribe_azure.py --episode 42 --delete-mp3
```

**What it does:**
1. Downloads the MP3 from the NPO feed URL to `data/mp3/{key}.mp3`
2. Posts the audio to the Azure MAI-Transcribe-2 REST endpoint (multipart)
3. Polls until the transcription job completes
4. Writes `data/transcripts/{key}.json` following the transcript schema (see `docs/transcript-schema.md`)
5. Deletes the MP3 when `--delete-mp3` is passed (the default for production runs)

**Speaker assignment:** Azure assigns speaker IDs `S1`, `S2`, … by word-count rank. The script maps them to real names: highest word count → David Boogerd; second (when Stefan Paas is in `episodes.json`) → Stefan Paas; remaining in order → guests. Manual overrides go in `data/speaker-corrections/{key}.json`:

```json
{ "1": "David Boogerd", "2": "Kader Abdolah", "3": "Stefan Paas" }
```

**Limits:** Azure MAI-Transcribe-2 accepts up to 2 hours / 250 MB per request. Episodes longer than 2 hours need splitting (not currently automated).

**Current status:** 210 transcripts (episodes 1–122 and 327). Episodes 123–326 have transcripts in the repo but have not been spot-checked.

**Fixing bad speaker counts:**

```bash
python scripts/fix_speaker_counts.py               # dry-run: report
python scripts/fix_speaker_counts.py --apply       # write corrected files
python scripts/fix_speaker_counts.py --episode 327 --apply
```

This removes ghost speakers (Azure diarization artefacts) by stripping extra IDs and reassigning their segments to the most recent valid speaker.

## Stage 3 — LLM analysis

Requires `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` in `.env`.

```bash
python scripts/analyze_episode.py --all-missing
python scripts/analyze_episode.py --episode 327
python scripts/analyze_episode.py --all-missing --model claude-sonnet-5-5 --force
```

**What it does:**
- Reads `data/feed/{key}.json` (description) and `data/transcripts/{key}.json` (segments)
- Sends a system prompt + user message to the Claude API (`claude-haiku-5-5` by default)
- System prompt is cached with `cache_control: ephemeral` — batch runs are very cheap (~$0.005/episode at Haiku 5.5 rates)
- Writes `data/analysis/{key}.json`

**Output fields** (`_AN_FIELDS` in `4_split_data.py`):

| Field | Description |
|---|---|
| `summary_tldr` | 2–3 sentence Dutch summary |
| `summary_points` | 5–10 bullet points (the "Kernpunten" section) |
| `chapters` | 4–8 chapters: `{start_seconds, title, summary}` |
| `highlights` | 3–6 notable moments: `{start_seconds, speaker, text, note}` |
| `bible_refs` | Only actual citations: `{ref, note}` — never general Bible mentions |
| `themes` | ≤4 theme labels from the fixed 18-theme list |
| `people` | Discussed persons: `{name, note}` |
| `books` | Named books with real discussion: `{title, author, note}` |
| `places` | Relevant geographic places |
| `quotes` | ≤3 verbatim quotes from the episode description |

**Important:** `max_tokens=8000` is required. At 6000, the LLM output gets truncated and `chapters`/`summary_points` are silently dropped.

**Current status:** 1 analysis (episode 327 only).

## Stage 4 — Build the site

```bash
python scripts/4_split_data.py
python scripts/5_build_site.py
```

**`4_split_data.py`** does:
1. Reads `data/episodes.json` and computes TF-IDF keywords (`kw`) per episode
2. Reads all `data/analysis/*.json` and indexes them by episode key
3. Reads all `data/transcripts/*.json` and builds aggregates:
   - `site/dist/data/speakers.json` — per-speaker stats across all transcripts
   - `site/dist/data/books/places/people.json` — mention aggregates (from `transcript.mentions[]`)
4. Writes `site/dist/data/episodes/{key}.json` — full episode data including `an` (analysis) where available
5. Writes `site/dist/data/index.json` — episode keys list

**`5_build_site.py`** does:
1. Reads all `site/dist/data/episodes/*.json`
2. Builds a lightweight inline index (only the fields needed for search + listing)
3. Inlines the index as JSON, plus SVG logos as base64 data URIs
4. Writes `site/dist/index.html`

**Light fields (inlined at page load):** `n t d s g p sj th f kw xs q r`
**Heavy fields (fetched on demand):** `x mp3 id sl an` — loaded via `fetchEpisodeDetail(e)` when a user opens an episode detail page.

**`site/dist/` is gitignored.** Run the build locally before viewing. The source of truth is `site/src/index.template.html`.
