# Feature inventory

| Page (route) | Features | Data |
| --- | --- | --- |
| Home `#start` | Hero with artwork, fact row (episodes, hours, guests, avg length), newest episodes, “around this day in earlier years”, most frequent guests, theme chips, “Verras me” random episode | Real |
| Afleveringen `#zoeken` | Full-text search over title, description, guests and number with highlighted snippets; filters: year range, theme, format, duration, Stefan Paas present; sort: relevance, newest, oldest, longest, shortest; “show spoken fragments with timestamp” toggle | Real (fragments: example) |
| Episode `#e-<nr>` | Title, date, duration, NPO + MP3 links; tabs **Overzicht** (summary, key points, who-speaks-when river, highlights, description), **Hoofdstukken** (chapter timeline), **Transcript** (searchable, follows player), **Analyse** (words, wpm, questions, laughs, interruptions, “God” count, speaking time and tempo per speaker, energy curve, verbal tics, longest monologue, vocabulary, Bible references, mentions by category, Ongelooflijke bingo); sidebar: cast, details, themes, keywords, people discussed, “Wist je dat” trivia; recommended and similar episodes; prev/next; demo player bar | Real metadata; transcript tabs example |
| Personen `#personen`, `#p-<slug>` | Filter and sort all people; person page: bio, fact row, timeline, per-year chart, all episodes, first/last/longest/shortest, themes, co-guests, word cloud, transcript stats (wpm vs average, share, words, tic, longest monologue, laughs) | Real; transcript panel example |
| Thema's `#themas`, `#t-<slug>` | 18 themes with per-year mini charts; theme page with share per year, guests, distinctive words, episodes | Real (keyword-based classification) |
| Statistieken `#statistieken` | Episodes and hours per year, average length, duration scatter, top guests by count and hours, theme heatmap, most-used/distinctive words per year or month, word-trend comparison, weekday, records; **Uit de transcripties**: fastest speakers, speaking share per year, laughs per hour, tic chart, Bible books, philosophers | Real; last section example |
| Genoemd `#genoemd`, `#m-<slug>` | People, philosophers, books, places mentioned in more than one episode: top-5 per category, filter/search/sort/minimum, sparkline per year, who says it most; name page with per-year chart, every mention with timestamp and speaker, who mentions it, co-mentioned names | Example (names in descriptions weighted) |
| Wie zei het? `#wie-zei-het` | Quiz: a real quote from a description, guess the guest's episode; running score | Real |

## Ideas not built yet

- Disagreement map: who contradicts or interrupts whom.
- Automatic reading list of every book mentioned, with links.
- Ask the archive a question and get answers that cite the exact moment.
- Shareable quote cards; “the archive in 10 minutes” highlight reels.
- How one theme (e.g. secularisation) develops across episodes over the years.
