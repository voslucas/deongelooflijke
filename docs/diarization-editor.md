# Diarization correction GUI

This native Python/Tkinter tool lets you listen to individual transcript lines,
correct their speaker assignments, and use trusted examples to reassign the rest
with Resemblyzer. All application code lives in `gui-tools/`.

## Install and start

From the repository root in PowerShell:

```powershell
# Use the project's existing environment, or create it first:
# python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe gui-tools/diarization_editor.py

# Open a particular episode immediately:
.venv\Scripts\python.exe gui-tools/diarization_editor.py --episode 327
```

Python 3.12+ with Tkinter is required. The normal Windows Python installer includes
Tkinter. Check it with `python -m tkinter`. On Linux you may need your distribution's
`python3-tk` package. Windows playback uses the built-in `winsound` module; macOS/Linux
playback additionally needs `python -m pip install sounddevice` and a working
PortAudio installation/audio device. No web server or transcription API key is needed.
Resemblyzer may download its pretrained model on first use; subsequent inference is local.

## Correct an episode

1. Select an episode from the dropdown. Episodes with a JSON transcript in
   `data/transcripts/` are listed, newest publication first, including unnumbered episodes.
2. Each line shows its number, start/end timestamps, complete transcript text,
   assigned name, **Listen** button, and **Correct** checkbox. Use Previous/Next
   to page through 30 lines at a time, or enter a line number and press Go.
3. Press **Listen** to play only that line's audio. **Stop audio** stops playback;
   listening to another line replaces the current clip.
4. Choose the right name from the line's dropdown. If someone is missing from the
   transcript's speaker list, use **Add speaker…**, then assign that name to the
   appropriate lines. This adds a speaker ID without renaming existing speakers.
5. Tick **Correct** only for lines whose speaker you have verified by listening.
   Every checkbox starts **false** when you open an episode. Choose clean speech
   from one person, preferably several seconds and several examples per person.
6. Press **FIX**. It needs checked examples for at least two different speakers.
   Provide examples for **every real participant you want FIX to identify**:
   only speakers with checked examples participate in automatic classification.
   The summary lists names without examples so you can check coverage first.
7. Review the new assignments and per-line cosine scores. Correct any mistakes,
   check more trusted examples, uncheck bad examples, and press **FIX** again as
   often as useful. Checked lines keep their assignments during every FIX.
8. Press **SAVE** to store exactly the speaker assignments currently displayed,
   including manual edits and accepted FIX results. Manual-only edits can be saved
   without running FIX or loading audio.

Changing a checked line's name also changes which speaker receives that example
on the next FIX. Automatic proposals are never checked automatically.

## How FIX works

For each checked line, the tool crops the episode's mono 16 kHz audio using the
transcript boundaries, preprocesses it with Resemblyzer (including silence removal),
and obtains a normalized voice embedding. It averages and normalizes the embeddings
for each selected speaker into a temporary `.npy` profile. A `profiles.json`
manifest records speaker IDs, names, filenames, and the source line numbers.

Each run builds a fresh `round-N` directory beneath an operating-system temporary
`diarization-editor-*` directory. Its path appears in the status bar. Profiles are
removed when you switch episodes or close the application normally. They are never
read from or written to `data/voice-profiles/`. Abnormal termination can leave
temporary directories behind; these can be removed when the tool is closed.

Every unchecked usable line is independently compared with all profiles built in
that run. The highest cosine similarity wins, with **no minimum score threshold**.
Scores are similarities, not probabilities. An exact tie, invalid interval,
empty speech, or failed embedding keeps that line's previous assignment and shows
a review status. An unusable **checked** example aborts FIX with its line number,
so an intended speaker is never silently dropped. A failed FIX leaves the displayed
assignments intact. FIX does not write the transcript.

The tool cannot split a line that contains multiple voices or resolve overlapping
speech. Avoid such lines as trusted examples. Very short speech, music, noise, or
similar voices can give unreliable matches; listen and review the results.

## Audio, saving, and backups

Audio loads on the first Listen or FIX action. Existing `data/mp3/{key}.mp3` files
are reused; otherwise the tool downloads from `source.audio` in the transcript,
falling back to the episode's `mp3` URL in `data/episodes.json`. Downloads remain
in the ignored `data/mp3/` cache for later sessions. You can place a matching MP3
there manually for offline use. The full decoded episode is held in memory while
open, so long recordings require additional RAM. Downloading, decoding, and voice
inference run in a background thread; editing and episode switching are disabled
until the operation finishes. The Stop audio button remains available.

SAVE makes a byte-for-byte timestamped backup beside the source transcript:
`data/transcripts/{key}.json.{UTC-timestamp}.bak`, then atomically replaces the
transcript. These local backups are ignored by Git. All existing text, timestamps, segment order, and other fields are
preserved; only selected speaker assignments and explicitly added speakers change.
To restore, close the tool and copy the desired backup over `{key}.json`.

Checked flags, scores, and profiles are session-only review aids. They are not
saved into the transcript. SAVE does not alter the separate Azure rank-override
files in `data/speaker-corrections/` or analysis data. Retranscribing an episode
can replace these line-level corrections. If another process changes the transcript
after you open it, SAVE refuses to overwrite it; reopen the episode to review the
new data. Switching episodes or closing with unsaved assignments offers Save,
Discard, or Cancel. Closing while background work runs asks you to wait for it.

The website reads the corrected source transcript after the next build/deployment.
Rebuild the production site from the repository root when ready:

```powershell
.venv\Scripts\python.exe scripts/4_split_data.py
.venv\Scripts\python.exe scripts/5b_build_site.py
```

## Troubleshooting and checks

- **No speech / unusable example:** uncheck that line and select a cleaner example.
- **Missing module:** install the root `requirements.txt` with the same Python
  interpreter you use to start the GUI.
- **Audio cannot be decoded:** verify the cached MP3 is complete and playable;
  replace a corrupt cached file, then reopen the episode.
- **No audio output:** check the default playback device and volume. On Linux/macOS,
  check `sounddevice`/PortAudio; Windows needs no extra playback package.
- **Only one speaker has examples:** select trusted lines for a second speaker
  before FIX. You can still make manual changes and SAVE.

Run the workflow tests without model downloads or an audio device:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_diarization_editor.py tests/test_reidentify_segments.py
```
