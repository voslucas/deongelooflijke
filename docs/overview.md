# Project overview

**Ongelooflijk Archief** is an unofficial, searchable archive of *De Ongelooflijke Podcast* (EO / NPO Radio 1). David Boogerd (host) and Stefan Paas (theologian, regular guest) talk with remarkable guests about faith in a secularising Netherlands. With 329+ episodes since 2019, the archive aims to be an IMDb-style reference: every episode, guest, theme, mentioned person, book and Bible verse — backed by real transcripts and LLM-extracted metadata.

## Key facts

| | |
|---|---|
| Episodes | 329 total (327 numbered + 2 unnumbered) as of Nov 2026 |
| Transcripts | 210 (episodes 1–122 and 327 at time of last commit; episodes 123–326 awaiting check) |
| Analyses | 1 (episode 327 only, via `claude-haiku-5-5`) |
| Site | Single self-contained HTML file — open `site/dist/index.html` directly |
| Language | Dutch interface and content throughout |

## What is real vs simulated

The site uses **real data** where it has it, and falls back gracefully otherwise:

| Feature | Status |
|---|---|
| Episode list, titles, dates, guests, themes | Real — from RSS feed + hand-compiled |
| Transcripts (speaker-diarised text) | Real for 210 episodes via Azure MAI-Transcribe-2 |
| Speaker river, transcript search, word counts | Real wherever a transcript exists |
| Chapters (Hoofdstukken tab) | Real only for ep 327; fallback: "beschikbaar zodra analyse klaar is" |
| Kernpunten, tldr (Overzicht tab) | Real only for ep 327; fallback: not shown |
| Highlights (Hoogtepunten) | Real for ep 327; fallback: derived from episode quotes |
| Mentioned people, books, places (Genoemd) | Stub (mentionAgg returns empty; views show placeholder) |
| Statistics from transcripts | Real speaker shares; laugh/interrupt counts not available from Azure |
| Bingo, Stopwoordjes | Real (computed from transcript text) |

## Repository layout

```
CLAUDE.md                   Design + code rules — read this first
README.md                   Setup and pipeline guide
design-system/
  README.md                 Brand book (typography, colours, voice)
  tokens.css                CSS custom properties (source of truth for colours)
  tokens.json               Same tokens as JSON
  Logos/                    Saint artwork + wordmark (not in git if large)
site/
  src/index.template.html   THE app — single HTML file, all CSS + JS inline
  dist/index.html           Built output (gitignored)
  dist/data/
    episodes/{key}.json     Full per-episode data including analysis (gitignored)
    transcripts/{key}.json  Served transcript files (gitignored)
    speakers.json           Aggregated speaker stats (gitignored)
    books/people/places.json Aggregated mention data (gitignored)
data/
  raw/feed.xml              Snapshot of the NPO RSS feed
  feed/{n}.json             Per-episode feed snapshots (329 files)
  transcripts/{n}.json      Per-episode transcripts (210 files; Azure output)
  analysis/{n}.json         Per-episode LLM analysis (1 file: 327)
  episodes.json             Compiled episode data (all episodes)
  themes.json               18 fixed themes
  speaker-corrections/      Manual speaker-ID overrides {1: "Name", 2: "Name"}
  intermediate/             Scratch output of build steps 1–3
  mp3/                      Downloaded audio files (gitignored, deleted after transcription)
scripts/                    See docs/pipeline.md
docs/                       This folder
tests/                      Pytest suite for scripts
.env                        API keys — gitignored, never commit
```

## External services

| Service | Used for | Credential |
|---|---|---|
| Azure MAI-Transcribe-2 | Speech-to-text with speaker diarization | `AZURE_SPEECH_KEY` + `AZURE_SPEECH_ENDPOINT` |
| Claude API (Anthropic) | LLM entity extraction and summarisation | `ANTHROPIC_API_KEY` or `CLAUDE_API_KEY` |
| NPO RSS feed | Episode metadata + MP3 URLs | None (public) |
| Google Fonts | Lora + Spectral typefaces | None (CDN) |

Credentials live in `.env` at the project root (never committed). The `.env` format is `KEY=value`, one per line, no quotes needed.
