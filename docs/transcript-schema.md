# Transcript data contract

Each `data/transcripts/{n}.json` is produced by `scripts/transcribe_azure.py` (Azure MAI-Transcribe-2). The analysis fields (`summary`, `chapters`, `highlights`) are populated separately by `scripts/analyze_episode.py` and stored in `data/analysis/{n}.json` — they are **not** written back into the transcript file. The site merges them at runtime.

## 1. Transcript file shape (`data/transcripts/{n}.json`)

```json
{
  "episode": 327,
  "source": {
    "audio": "https://podcast.npo.nl/file/…/kader-abdolah-….mp3",
    "model": "azure/mai-transcribe-2",
    "created": "2026-11-08"
  },
  "speakers": [
    { "id": "S1", "name": "David Boogerd", "role": "host" },
    { "id": "S2", "name": "Stefan Paas",   "role": "guest" },
    { "id": "S3", "name": "Kader Abdolah", "role": "guest" }
  ],
  "segments": [
    { "start": 12.4, "end": 41.9, "speaker": "S1", "text": "Welkom bij De Ongelooflijke…" }
  ],
  "events": [],
  "summary":   { "tldr": "", "points": [] },
  "chapters":  [],
  "highlights": [],
  "mentions":  [],
  "bible":     []
}
```

**Fields produced by Azure + the transcription script:**
- `speakers[]` — speaker IDs mapped to real names (see speaker assignment below)
- `segments[]` — start/end seconds, speaker ID, text

**Fields left empty by transcription, used by the site if populated:**
- `summary`, `chapters`, `highlights` — filled from `data/analysis/{n}.json` at runtime
- `mentions`, `bible` — not currently filled; mention aggregation will come from analysis
- `events` — Azure doesn't produce laugh or overlap events; the array is always empty

## 2. Analysis file shape (`data/analysis/{n}.json`)

Written by `analyze_episode.py`, stored separately. The site's `4_split_data.py` reads these and places a subset (`_AN_FIELDS`) into the per-episode dist file under the `an` key.

```json
{
  "episode": 327,
  "analyzed": "2026-11-11",
  "model": "claude-haiku-5-5",
  "summary_tldr": "2–3 sentence Dutch summary of the episode.",
  "summary_points": ["Kernpunt 1", "Kernpunt 2"],
  "chapters": [
    { "start_seconds": 95, "title": "Introductie", "summary": "…" }
  ],
  "highlights": [
    { "start_seconds": 898, "speaker": "Kader Abdolah", "text": "Castro en Che…", "note": "Waarom dit opvalt." }
  ],
  "bible_refs": [{ "ref": "Mattheus 7:7", "note": "context" }],
  "themes": ["Bijbel & Jezus", "God & geloof"],
  "guests": ["Kader Abdolah"],
  "people": [{ "name": "Karl Marx", "note": "filosoof" }],
  "books": [{ "title": "Jezus", "author": "Kader Abdolah", "note": "…" }],
  "places": ["Iran", "Nederland"],
  "quotes": ["citaat uit de beschrijving"]
}
```

`bible_refs` only contains actual citations (a specific verse or chapter quoted/referenced), never a general mention of "the Bible".

## 3. Speaker assignment

Azure assigns IDs `S1`, `S2`, … by word-count rank (most words = `S1`). The script maps them to real names:

1. Highest word count → **David Boogerd** (always present as host)
2. Second (only when `episodes.json` has `p: true`) → **Stefan Paas**
3. Remaining in order → guests from `episodes.json` `g[]`

Manual overrides: create `data/speaker-corrections/{n}.json` as `{"1": "Name", "2": "Name"}`. The key is the Azure-assigned numeric rank (1 = most words). `fix_speaker_counts.py` can also remove ghost speakers (extra IDs from Azure diarization artefacts).

## 4. The T-object (browser side)

`buildTFromRaw(raw, e)` converts the raw transcript JSON (after `e.an` is merged in) into the T-object the views consume. See `docs/site-architecture.md` for the full field list.

The merge happens in `fetchTranscript(e)` before `buildTFromRaw` is called:

```javascript
const an = e.an;  // set by fetchEpisodeDetail
if (an) {
  if (an.summary_tldr || an.summary_points?.length)
    raw.summary = { tldr: an.summary_tldr || '', points: an.summary_points || [] };
  if (an.chapters?.length)
    raw.chapters = an.chapters.map(c => ({ start: c.start_seconds, title: c.title, summary: c.summary || '' }));
  if (an.highlights?.length)
    raw.highlights = an.highlights.map(h => ({ t: h.start_seconds, kind: h.note || 'Hoogtepunt', speaker: nameId[h.speaker], text: h.text }));
  if (an.bible_refs?.length)
    raw.bible = an.bible_refs.map(b => ({ ref: b.ref, t: -1 }));
  raw._hasAnalysis = true;
}
```

`_hasChapters` is computed **before** the fallback chapter is inserted:
```javascript
const _hasChapters = raw.chapters.length > 0;
// fallback: if no real chapters, insert one spanning the full episode
if (!chapters.length) chapters.push({ ... title: e.t, ... });
```

This flag gates the chapter tab: when false, the tab shows "beschikbaar zodra de analyse klaar is".
