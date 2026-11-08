# Transcript data contract

The episode pages, person pages, statistics and the Genoemd page already render a full transcript layer. Today `transcriptFor(e)` builds it from the episode description plus a seeded random generator. To go live, produce one JSON file per episode in the shape below, embed or load it, and have `transcriptFor(e)` return the derived object (section 2) from it. No view needs to change.

## 1. Input: what a transcription pipeline should produce

One file per episode, e.g. `data/transcripts/327.json`:

```json
{
  "episode": 327,
  "source": { "audio": "https://podcast.npo.nl/file/…/kader-abdolah-….mp3", "model": "whisper-large-v3 + pyannote 3.1", "created": "2026-11-08" },
  "speakers": [
    { "id": "S1", "name": "David Boogerd", "role": "Presentator" },
    { "id": "S2", "name": "Stefan Paas", "role": "Vaste gast" },
    { "id": "S3", "name": "Kader Abdolah", "role": "Gast" }
  ],
  "segments": [
    { "start": 12.4, "end": 41.9, "speaker": "S1", "text": "Welkom bij De Ongelooflijke Podcast…" }
  ],
  "events": [
    { "t": 270.2, "type": "laugh", "speaker": "S3", "size": 2 },
    { "t": 1844.0, "type": "overlap", "speakers": ["S1", "S3"] }
  ],
  "summary": { "tldr": "…", "points": ["…", "…"] },
  "chapters": [ { "start": 0, "title": "Een verboden boek in de bibliotheek", "summary": "…" } ],
  "highlights": [ { "t": 898.0, "kind": "Uitspraak", "speaker": "S3", "text": "Castro en Che Guevara waren mijn helden." } ],
  "mentions": [
    { "name": "Augustinus", "type": "filosoof", "t": 2210.5, "speaker": "S2" },
    { "name": "Iran", "type": "plaats", "t": 95.0, "speaker": "S3" },
    { "name": "Belijdenissen", "type": "boek", "t": 2214.0, "speaker": "S2" }
  ],
  "bible": [ { "ref": "Lucas 15", "t": 3302.0, "speaker": "S2" } ]
}
```

Notes:
- Times are seconds from the start of the MP3.
- `speakers[].name` must match the names used in `data/episodes.json` (guests in `g`, plus “David Boogerd” and “Stefan Paas”), so person pages link up.
- `mentions[].type` is one of `persoon`, `filosoof`, `boek`, `plaats`. One entry per spoken mention (not per episode). Normalise names to one canonical spelling (e.g. “Søren Kierkegaard”, not “Kierkegaard”).
- `summary`, `chapters` and `highlights` can come from a language model run over the segments; `events` from audio analysis (laughter detection, overlapping speech in diarization).

## 2. Output: the object the UI reads (`T = transcriptFor(e)`)

| Field | Type | Derived from |
| --- | --- | --- |
| `D` | seconds | episode duration |
| `spk[]` | `{name, role, c, time, share, wpm, words, turns, longest, longestSeg, ttr, tics{}, questions}` | segments per speaker: `time` = sum of durations, `share` = time / D, `words` from text, `wpm` = words / minutes, `longestSeg` = longest segment, `ttr` = unique words / words (per 1,000-word window), `tics` = counts of the phrases in `TICS`, `questions` = segments ending in “?” |
| `segs[]` | `{i, sp, t, start, end, dur}` | segments (`sp` points to the `spk` entry) |
| `chapters[]` | `{j, start, end, title, sum, who[]}` | chapters; `end` = next chapter's start; `who` = speakers in that range |
| `laughs[]` | `{t, who, size}` | events of type `laugh` |
| `interrupts` | number | events of type `overlap` |
| `energy[]` | 80 numbers 0–1 | loudness × speaking rate, resampled to 80 points |
| `tldr`, `points[]` | text | summary |
| `hls[]` | `{t, kind, html, who}` | highlights, plus computed “Grootste lachsalvo”, “Langste monoloog”, “Meest geanimeerd” |
| `bible[]` | `{b, t}` | bible |
| `ment[]` | `{n, c, x, hits[{t, sp}], real}` | mentions grouped by name: `x` = count, `hits` = each mention |
| `god` | number | count of “God” in the text |
| `bingo[]` | `{b, hit, t}` | first match of each phrase in `BINGO` |

Speaker colours (`c`) are assigned by role, see `CLAUDE.md`.

## 3. Swapping it in

1. Add the transcripts to the build (e.g. `scripts/5_build_transcripts.py` → `data/transcripts.json`, inlined like `episodes.json`, or published next to the page and fetched).
2. In `transcriptFor(e)`: if a transcript exists for `e.n`, build `T` from it as in the table; otherwise return `null`.
3. Where `T` is `null`, the episode page should show the description only (as trailers do now) and aggregates should skip that episode.
4. Remove the `.demo` badges and `.demonote` lines from views whose data is now real.
