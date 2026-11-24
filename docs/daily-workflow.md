# Daily episode processing

The daily workflow (`.github/workflows/new-episodes.yml`) runs at 07:00 UTC:
08:00 Amsterdam in winter and 09:00 in summer. It can also be started manually.

The source is `https://podcast.npo.nl/feed/de-ongelooflijke-podcast.xml`.
The previous Omny URL returned HTTP 404. `scripts/fetch_feed.py` checks the RSS
structure, podcast title and audio enclosures before replacing the saved feed.
The production build uses the same downloader and retains its committed snapshot
when downloading fails; daily processing fails visibly instead of using stale data.

## Processing order

1. Download the feed and run stages 1–3 to refresh feed snapshots and master records.
2. Find missing transcripts/analyses and unfinished processing records. Unnumbered
   episodes use their canonical `x{id}` keys. Existing archive analyses are preserved.
3. Transcribe each pending episode with Azure, then attempt voice identification.
4. Analyse the **complete timestamped transcript, including speaker names**, using
   `claude-haiku-5-5`. There is no character cutoff. The saved `transcript_input`
   records character/segment counts and `truncated: false`. Output reaching its
   token limit is rejected instead of saving an incomplete extraction.
   Theme labels must exactly match `data/themes.json` (at most four distinct
   labels). Unknown labels, including labels with keyword hints appended, fail
   before enrichment or saving. Stage 4 also validates master and analysis themes
   before writing output, so stale or manually edited data cannot add categories.
5. Verify book matches and recommend related episodes (part of the analysis script).
6. Enrich mentioned people with Wikipedia, fetch missing book details for the
   episode, and generate missing biographies for its cast. Existing biographies
   are preserved. Analysed guest names take precedence over feed heuristics.
7. Add the episode to the Dutch spaCy word index and collect mentioned-person
   profiles across the archive.
8. Fetch missing book covers, split the site data, build the static site and test.
9. Commit all tracked data, including processing state, Wikipedia cache, profiles,
   book details, covers, biographies and word statistics. Generated site output
   and downloaded audio remain ignored.
10. Explicitly dispatch `build.yml` after a successful changed run. A push made
    using `GITHUB_TOKEN` does not itself trigger the push-based deployment workflow.

`data/processing/{key}.json` records completed stages. A failed run saves its
progress and exits unsuccessfully. The workflow commits that progress even on
failure so a later run can resume. Voice identification remains best effort and
records a warning if it fails. No catalogue match for a book is a valid outcome;
missing reference material is not invented. Audio is deleted after successful
episode processing. Failed jobs can retain local audio until the runner is removed.

Azure upload progress is reported separately from transcription: percentage,
bytes, average MB/s and elapsed time count the multipart request as it is sent.
After the final chunk, the script prints `Upload finished ...; waiting for Azure
to finish transcription ...`. This remains one HTTP request; the waiting phase
has no server-side completion percentage. Both httpx and the requests fallback
stream the file rather than buffering the entire multipart body in memory.

## Local verification and rollout

Run from the repository root. In Windows PowerShell, enable UTF-8 before invoking
the scripts (the older stages use Python's default file encoding):

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONUNBUFFERED='1'
.\.venv\Scripts\python.exe scripts/fetch_feed.py
.\.venv\Scripts\python.exe scripts/1_parse_feed.py
.\.venv\Scripts\python.exe scripts/2_extract_guests.py
.\.venv\Scripts\python.exe scripts/3_build_episode_data.py
.\.venv\Scripts\python.exe scripts/process_new_episodes.py --plan
.\.venv\Scripts\python.exe scripts/process_new_episodes.py --episode 328
.\.venv\Scripts\python.exe scripts/book_covers.py
.\.venv\Scripts\python.exe scripts/4_split_data.py
.\.venv\Scripts\python.exe scripts/5b_build_site.py
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

Stop if any command fails. Credentials are loaded from local `.env` files, or
provided by Actions secrets: `AZURE_SPEECH_KEY`, `AZURE_SPEECH_ENDPOINT`,
`CLAUDE_API_KEY` (passed as `ANTHROPIC_API_KEY`) and optional `GOOGLE_BOOKS_API_KEY`.
Install dependencies from `requirements.txt`, plus pytest, and install spaCy's
`nl_core_news_sm` model. Actions installs that Dutch model explicitly.

The agreed rollout is #328 locally, then #329 and #330 in Actions. Episode #331 is
held in `data/pipeline-settings.json`; both automatic and explicit processing
refuse held keys. Remove that key when ready to release the hold. Its feed record
can still appear on the site, without a transcript or analysis.

Older episodes are **not** automatically reanalysed. A future archive reanalysis
requires a separate decision and an explicit forced run. A normal pending run
never replaces an existing analysis just because it lacks the new coverage metadata.

Related-episode selection has a separate output allowance (4,000 tokens, retrying
invalid or truncated responses once with 8,000). If it still fails, the main
extraction and book matches are saved with `similar_status: failed`, and the
command exits unsuccessfully. Daily processing retries only this failed lookup.
For a manual repair without reanalysing the transcript or rematching books:

```powershell
.\.venv\Scripts\python.exe scripts/analyze_episode.py --episode 327 --similar-only
```

See [Anthropic's Haiku documentation](https://platform.claude.com/docs/en/models/haiku-5-5/overview)
for the model ID and context capacity, and
[GitHub's workflow trigger documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
for the bot-push restriction.
