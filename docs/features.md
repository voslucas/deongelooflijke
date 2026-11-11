# Feature inventory

Status column: **Real** = data from feed/transcripts/analysis; **Partial** = real for episodes with transcripts; **Stub** = placeholder, no data yet.

| Page (route) | Features | Status |
|---|---|---|
| Home `#start` | Hero with saint artwork, fact row (episodes, hours, guests, avg length), newest episodes, "around this day in earlier years", most frequent guests, theme chips, "Verras me" random episode | Real |
| Afleveringen `#zoeken` | Full-text search over title, description, guests and number with highlighted snippets; filters: year range, theme, format, duration, Stefan Paas present, transcript available; sort: relevance, newest, oldest, longest, shortest; "show spoken fragments" toggle | Real (fragments require transcript in TX cache) |
| Episode `#e-<nr>` — Overzicht tab | Speaker river with share%; "In het kort" (tldr) + Kernpunten bullet list; Hoogtepunten (highlights); description; recommended episodes | Real for all (river); Real for ep 327 (tldr + Kernpunten + highlights); Real for all (description) |
| Episode `#e-<nr>` — Hoofdstukken tab | Chapter list with timestamps, summaries, speaker lists | Real for ep 327; placeholder message for all others |
| Episode `#e-<nr>` — Transcript tab | Searchable, speaker-colour-coded transcript; timestamp seek buttons | Partial (210 episodes) |
| Episode `#e-<nr>` — Analyse tab | Word count, wpm, questions from David, "God" count; speaking time per speaker, tempo, longest monologue, vocabulary (TTR); energy curve (speech density); stopwoordjes (verbal tics); Bible references; Ongelooflijke bingo | Partial — most tiles real where transcript exists; Bible refs real for ep 327 only |
| Episode sidebar | Cast, format, date/duration, themes, keywords, people discussed, "Wist je dat" trivia | Real |
| Episode — prev/next/similar | Navigation by number; similar episodes via TF-IDF cosine similarity | Real |
| Personen `#personen` | Filter and sort all guests by count | Real |
| Persoon `#p-<slug>` | Bio, fact row, timeline, per-year chart, all episodes, first/last/longest/shortest, themes, co-guests | Real; transcript stats partial |
| Thema's `#themas` | 18 themes with per-year mini charts | Real (keyword-based classification) |
| Thema `#t-<slug>` | Share per year, guests, distinctive words, episodes | Real |
| Statistieken `#statistieken` | Episodes and hours per year, average length, duration scatter, top guests, theme heatmap, most-used/distinctive words, records | Real; speaker stats partial (requires transcripts) |
| Genoemd `#genoemd` | People, books, places mentioned across episodes | Stub — `mentionAgg()` returns empty; mention extraction requires analysis for each episode |
| Mention `#m-<slug>` | Per-name page with timeline, who says it, co-mentioned names | Stub |
| Wie zei het? `#wie-zei-het` | Quiz: guess which episode a quote is from | Real (quotes from episode descriptions) |

## What's needed to unlock each feature fully

| Feature | Blocker |
|---|---|
| Kernpunten, Hoofdstukken, Highlights | Run `analyze_episode.py --all-missing` for all 210 transcribed episodes |
| Transcript for 123–326 | Spot-check speaker assignments; consider `fix_speaker_counts.py` |
| Transcript for 123–326 on site | Run `4_split_data.py && 5_build_site.py` |
| Genoemd / mention pages | Run `analyze_episode.py --all-missing`; then populate `transcript.mentions[]` from `analysis.people/books/places` |
| Bible reference stats in Statistieken | Run analysis for all episodes |
| Speaker stats in Statistieken | Transcripts already exist; rebuild with `4_split_data.py` |
| Remaining 119 episodes (328, 329, etc.) | Transcribe with `transcribe_azure.py` |

## Ideas not built yet

- Disagreement map: who contradicts or interrupts whom.
- Automatic reading list of every book mentioned, with links.
- Ask the archive a question and get answers that cite the exact moment.
- Shareable quote cards; "the archive in 10 minutes" highlight reels.
- How one theme (e.g. secularisation) develops across episodes over the years.
- Full-text search within transcripts across all episodes (currently only the already-cached TX entries are searched).
