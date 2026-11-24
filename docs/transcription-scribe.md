# ElevenLabs Scribe v3 transcription

`scripts/transcribe.py` restores the former ElevenLabs entry point with Scribe v3.
It uses the same JSON contract as `transcribe_azure.py`, including speaker IDs,
Dutch roles, timestamped segments in seconds, empty analysis containers and
`events: []`. Provenance is `elevenlabs/scribe_v3`.

```powershell
.\.venv\Scripts\python.exe scripts/transcribe.py --episode 331
.\.venv\Scripts\python.exe scripts/transcribe.py --all-missing --identify --delete-mp3
.\.venv\Scripts\python.exe scripts/transcribe.py --probe
```

The main MAI options are also available here: `--episode`, `--all-missing`,
`--probe`, `--key`, `--endpoint`, `--identify`, and `--delete-mp3`.
`--api-key` is an alias for `--key` retained from the old ElevenLabs script.
Set `ELEVENLABS_API_KEY` in your environment or local `.env`; no ElevenLabs SDK
is needed beyond the existing `httpx` dependency. The endpoint defaults to
`https://api.elevenlabs.io` and accepts an API base URL.

Scribe receives Dutch, verbatim transcription, word timestamps, diarization,
disabled audio-event tagging and `num_speakers = 1 + bool(p) + len(g)` from the
episode metadata. This supplies the known cast count to the model, rather than
only restricting speaker names after transcription. ElevenLabs describes this
parameter as a maximum, so fewer speakers may be returned. See the
[official API contract](https://elevenlabs.io/docs/api-reference/speech-to-text/convert).

Words become segments at speaker changes, sentence endings, pauses over one
second or twenty seconds of speech. Spacing and audio-event tokens are excluded.
Speaker names use MAI's word-count ranking heuristic: David, Stefan when `p` is
true, then the guests in metadata order. This heuristic can misidentify people;
`--identify` runs the existing voice-profile matching on the **new output file**.
Unassigned or unexpected clusters retain separate generic labels and their speech.
Existing manual `data/corrections/{key}.json` overrides apply to the canonical
speaker IDs, as supported by the MAI helper.

Like MAI, the script downloads audio to `data/mp3/{key}.mp3`, reuses an existing
nonempty cached MP3, and uploads the local file to ElevenLabs. Downloads follow
redirects and stream to a temporary file; interrupted or empty downloads never
become cache hits. The MP3 stays available for voice identification and retries.
`--delete-mp3` removes it only after successful transcription and identification.

Existing output files are always skipped; exclusive file creation also prevents
overwriting if another process creates the file during transcription. To compare
providers, specify a separate file or directory:

```powershell
.\.venv\Scripts\python.exe scripts/transcribe.py --episode x5005 --output data/transcription-tests/x5005.scribe-v3.json
.\.venv\Scripts\python.exe scripts/transcribe.py --episode 250 --output-dir data/transcription-tests/scribe-v3
```

`--all-missing` checks the chosen output directory (default `data/transcripts`).
Unnumbered episodes use `x` plus their feed ID. HTTP 429 is retried once after
`Retry-After`; failed runs return a nonzero exit status. The existing scheduled
pipeline continues to select MAI; use this entry point to run Scribe explicitly.

## Live verification (24 November 2026)

The shortest feed item, the 53-second trailer (`x5005`), was transcribed with
Scribe v3 and `num_speakers=2`. The result is saved separately as
`data/transcription-tests/x5005.scribe-v3.json`: 22 segments, speech timestamps
from 0.14 to 51.52 seconds, valid speaker references and no events. The original
`data/transcripts/x5005.json` remained byte-for-byte identical to Git HEAD.
The trailer contains a montage of voices; Scribe returned ten speaker clusters
despite the count hint. Extra clusters are preserved with generic names instead
of assigning their speech to the host. The script warns when this happens.
