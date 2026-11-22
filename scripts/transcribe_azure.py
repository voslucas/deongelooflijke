"""Transcribe a podcast episode via Microsoft MAI-Transcribe-2 with speaker diarization.

Usage:
    python scripts/transcribe_azure.py --episode N [--key KEY] [--endpoint URL]
    python scripts/transcribe_azure.py --all-missing [--key KEY] [--endpoint URL]
    python scripts/transcribe_azure.py --probe               # test region support

Credentials are read from --key/--endpoint, then AZURE_SPEECH_KEY / AZURE_SPEECH_ENDPOINT
env vars, then .env file.

Output: data/transcripts/{key}.json  (transcript-schema.md input shape)

API:
    POST https://{resource}.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15
    multipart/form-data  (audio + definition)
    Auth: Ocp-Apim-Subscription-Key header
    Limits: ≤ 2 hours, ≤ 250 MB per request
"""
import argparse, datetime, json, os, pathlib, re, sys, time, uuid
from utils import ep_key as _ep_key

ROOT = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON = ROOT / 'data' / 'episodes.json'
OUT_DIR = ROOT / 'data' / 'transcripts'
MP3_DIR = ROOT / 'data' / 'mp3'
CORRECTIONS_DIR = ROOT / 'data' / 'corrections'

API_VERSION = '2025-10-15'

try:
    import requests as _requests
except ImportError:
    _requests = None

try:
    import httpx as _httpx
except ImportError:
    _httpx = None


class RateLimitError(Exception):
    def __init__(self, retry_after=60):
        self.retry_after = retry_after
        super().__init__(f'Rate limited; retry after {retry_after}s')


class TranscriptionError(Exception):
    pass


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def _load_credentials(explicit_key=None, explicit_endpoint=None):
    key = explicit_key or os.environ.get('AZURE_SPEECH_KEY')
    endpoint = explicit_endpoint or os.environ.get('AZURE_SPEECH_ENDPOINT')
    env_file = ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            if not key and line.startswith('AZURE_SPEECH_KEY='):
                key = line.split('=', 1)[1].strip().strip('"\'')
            if not endpoint and line.startswith('AZURE_SPEECH_ENDPOINT='):
                endpoint = line.split('=', 1)[1].strip().strip('"\'')
    return key, endpoint


def _transcribe_url(endpoint):
    base = endpoint.rstrip('/')
    return f'{base}/speechtotext/transcriptions:transcribe?api-version={API_VERSION}'


def _download_mp3(mp3_url, dest_path, requests):
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    print(f'  Downloading {mp3_url} …')
    dl = requests.get(mp3_url, timeout=(30, 600), stream=True)
    if not dl.ok:
        raise TranscriptionError(f'Could not download MP3: HTTP {dl.status_code}')
    total = int(dl.headers.get('Content-Length', 0))
    done = 0
    with open(dest_path, 'wb') as f:
        for chunk in dl.iter_content(65536):
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 // total
                print(f'\r  {pct}% ({done // 1_000_000} / {total // 1_000_000} MB)',
                      end='', flush=True)
    print()
    print(f'  Saved to {dest_path.relative_to(ROOT)}  ({done // 1_000_000} MB)')


# ---------------------------------------------------------------------------
# Speaker mapping (integer IDs from Azure → canonical names)
# ---------------------------------------------------------------------------

def _speaker_map(phrases, ep):
    """Map Azure speaker integers to canonical names by word-count rank.

    Azure diarization often returns more speaker IDs than actual participants
    (e.g. intro voices, music fragments).  Cap the mapping to the expected
    number of speakers derived from the feed data so spurious IDs are excluded.
    """
    counts: dict[int, int] = {}
    for ph in phrases:
        sid = ph.get('speaker')
        if sid is not None:
            counts[sid] = counts.get(sid, 0) + len(ph.get('words', [ph]))
    ranked = [sid for sid, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)]

    guests = ep.get('g', [])
    has_paas = ep.get('p', False)
    expected = 1 + (1 if has_paas else 0) + len(guests)
    # Only map the top-N speakers; ignore the rest so they fall through to
    # the fallback label in _azure_to_transcript and can be spotted easily.
    ranked = ranked[:expected]

    mapping: dict[int, tuple[str, str]] = {}
    for i, sid in enumerate(ranked):
        if i == 0:
            mapping[sid] = ('David Boogerd', 'Presentator')
        elif i == 1 and has_paas:
            mapping[sid] = ('Stefan Paas', 'Vaste gast')
        else:
            guest_idx = i - 1 - (1 if has_paas else 0)
            if 0 <= guest_idx < len(guests):
                mapping[sid] = (guests[guest_idx], 'Gast')
            else:
                mapping[sid] = (f'Spreker {i + 1}', 'Gast')
    return mapping


# ---------------------------------------------------------------------------
# Convert Azure response → transcript-schema.md
# ---------------------------------------------------------------------------

def _azure_to_transcript(response_json, mapping, ep):
    phrases = response_json.get('phrases', [])

    # Build speakers list
    seen: list[tuple[str, str]] = []
    for entry in mapping.values():
        if entry not in seen:
            seen.append(entry)
    name_to_id = {entry[0]: f'S{i + 1}' for i, entry in enumerate(seen)}
    speakers = [{'id': name_to_id[entry[0]], 'name': entry[0], 'role': entry[1]}
                for entry in seen]

    segments = []
    events = []
    prev_speaker = None
    prev_end_ms = None

    for ph in phrases:
        azure_sid = ph.get('speaker')
        entry = mapping.get(azure_sid, (f'Spreker {azure_sid}', 'Gast'))
        name = entry[0]
        sid = name_to_id.get(name, 'S1')
        start_s = ph.get('offsetMilliseconds', 0) / 1000
        end_s = start_s + ph.get('durationMilliseconds', 0) / 1000

        # Overlap event when speaker switches with tiny gap
        if prev_speaker and prev_speaker != sid and prev_end_ms is not None:
            gap_ms = ph.get('offsetMilliseconds', 0) - prev_end_ms
            if gap_ms < 300:
                events.append({
                    't': round(prev_end_ms / 1000, 3),
                    'type': 'overlap',
                    'speakers': [prev_speaker, sid],
                })

        segments.append({
            'start': round(start_s, 3),
            'end': round(end_s, 3),
            'speaker': sid,
            'text': ph.get('text', ''),
        })
        prev_speaker = sid
        prev_end_ms = ph.get('offsetMilliseconds', 0) + ph.get('durationMilliseconds', 0)

    return {
        'episode': ep.get('n'),
        'source': {
            'audio': ep.get('mp3', ''),
            'model': 'azure/mai-transcribe-2',
            'created': datetime.date.today().isoformat(),
        },
        'speakers': speakers,
        'segments': segments,
        'events': events,
        'summary': {'tldr': '', 'points': []},
        'chapters': [],
        'highlights': [],
        'mentions': [],
        'bible': [],
    }


# ---------------------------------------------------------------------------
# Manual speaker corrections
# ---------------------------------------------------------------------------

def _apply_corrections(transcript, ep_key_str):
    """Apply manual speaker name corrections from CORRECTIONS_DIR/{ep_key_str}.json.

    The correction file is a dict mapping speaker IDs (e.g. "S2") to the
    corrected name string.  Returns the (possibly modified) transcript dict.
    """
    path = CORRECTIONS_DIR / f'{ep_key_str}.json'
    if not path.exists():
        return transcript
    try:
        corrections = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return transcript
    for sp in transcript.get('speakers', []):
        if sp['id'] in corrections:
            new_name = corrections[sp['id']]
            old_name = sp['name']
            sp['name'] = new_name
            for seg in transcript.get('segments', []):
                pass  # segments use speaker IDs, not names
            _ = old_name  # name reference kept for potential future use
    return transcript


# ---------------------------------------------------------------------------
# MP3 cleanup
# ---------------------------------------------------------------------------

def _delete_mp3(ep_key):
    mp3_path = MP3_DIR / f'{ep_key}.mp3'
    if mp3_path.exists():
        mp3_path.unlink()
        print(f'  Deleted {mp3_path.relative_to(ROOT)}')


# ---------------------------------------------------------------------------
# Main transcription call
# ---------------------------------------------------------------------------

class _AzureUpload:
    """Stream a length-delimited multipart body and report bytes after each send.

    Both HTTP clients consume this iterator as they write the request body. The
    code after each yield runs once the client has sent that chunk, rather than
    while a multipart encoder is merely reading the file into memory.
    """

    def __init__(self, audio, filename, definition):
        self.audio = audio
        boundary = uuid.uuid4().hex
        self.content_type = f'multipart/form-data; boundary={boundary}'
        # Episode filenames are local canonical keys, not arbitrary user input.
        self.prefix = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="audio"; filename="{filename}"\r\n'
            'Content-Type: audio/mpeg\r\n\r\n'
        ).encode('utf-8')
        self.suffix = (
            f'\r\n--{boundary}\r\n'
            'Content-Disposition: form-data; name="definition"\r\n'
            'Content-Type: application/json\r\n\r\n'
            + json.dumps(definition) + f'\r\n--{boundary}--\r\n'
        ).encode('utf-8')
        self.total = len(self.prefix) + os.fstat(audio.fileno()).st_size + len(self.suffix)

    def __len__(self):
        return self.total

    def _chunks(self):
        self.audio.seek(0)
        yield self.prefix
        while chunk := self.audio.read(65536):
            yield chunk
        yield self.suffix

    def __iter__(self):
        started = time.monotonic()
        sent, last_percent, last_update = 0, 0, started
        inline = sys.stdout.isatty()
        print(f'  Upload:   0% (0.0 / {self.total / 1_000_000:.1f} MB)',
              end='\r' if inline else '\n', flush=True)
        for chunk in self._chunks():
            yield chunk
            sent += len(chunk)
            now = time.monotonic()
            percent = sent * 100 // self.total
            if percent != last_percent or now - last_update >= 2:
                elapsed = now - started
                speed = sent / max(elapsed, 0.001) / 1_000_000
                print(f'  Upload: {percent:3d}% '
                      f'({sent / 1_000_000:.1f} / {self.total / 1_000_000:.1f} MB) '
                      f'| {speed:.2f} MB/s | {elapsed:.0f}s elapsed',
                      end='\r' if inline else '\n', flush=True)
                last_percent, last_update = percent, now
        if inline:
            print(flush=True)
        print(f'  Upload finished in {time.monotonic() - started:.1f}s; '
              'waiting for Azure to finish transcription ...', flush=True)


def transcribe_episode(ep, key, endpoint, requests):
    mp3_url = ep.get('mp3', '')
    if not mp3_url:
        raise TranscriptionError('No mp3 URL for this episode')

    ep_key = _ep_key(ep)
    mp3_path = MP3_DIR / f'{ep_key}.mp3'
    if mp3_path.exists():
        print(f'  Using cached MP3: {mp3_path.relative_to(ROOT)}')
    else:
        _download_mp3(mp3_url, mp3_path, requests)

    definition = {
        'locales': ['nl'],
        'diarization': {'enabled': True},
        'enhancedMode': {
            'enabled': True,
            'model': 'MAI-Transcribe-2',
            'modelOptions': {
                'timestamps': 'word',
                'transcribeStyle': 'verbatim',
            },
        },
    }

    url = _transcribe_url(endpoint)
    headers = {'Ocp-Apim-Subscription-Key': key}

    mb = mp3_path.stat().st_size // 1_000_000
    print(f'  Uploading {mb} MB to MAI-Transcribe-2 …', flush=True)

    with open(mp3_path, 'rb') as audio_f:
        upload = _AzureUpload(audio_f, mp3_path.name, definition)
        upload_headers = {
            **headers,
            'Content-Type': upload.content_type,
            'Content-Length': str(len(upload)),
        }
        # httpx avoids the Windows SSLWantWriteError on large HTTPS uploads
        if _httpx is not None:
            with _httpx.Client(timeout=_httpx.Timeout(60, read=7200)) as client:
                resp_raw = client.post(
                    url,
                    headers=upload_headers,
                    content=upload,
                )
            status_code = resp_raw.status_code
            retry_after = resp_raw.headers.get('Retry-After', 60)
            response_text = resp_raw.text
            try:
                response_json_data = resp_raw.json()
            except Exception:
                response_json_data = None
        else:
            resp_raw = requests.post(
                url,
                headers=upload_headers,
                data=upload,
                timeout=(60, 7200),
            )
            status_code = resp_raw.status_code
            retry_after = resp_raw.headers.get('Retry-After', 60)
            response_text = resp_raw.text
            try:
                response_json_data = resp_raw.json()
            except Exception:
                response_json_data = None

    if status_code == 429:
        raise RateLimitError(int(retry_after))
    if status_code >= 400:
        raise TranscriptionError(
            f'Azure API error {status_code}: {response_text[:300]}'
        )

    data = response_json_data
    phrases = data.get('phrases', [])
    print(f'  Got {len(phrases)} phrases')

    mapping = _speaker_map(phrases, ep)
    transcript = _azure_to_transcript(data, mapping, ep)
    return transcript


# ---------------------------------------------------------------------------
# Probe: check if the endpoint supports LLM Speech / MAI-Transcribe-2
# ---------------------------------------------------------------------------

def probe(key, endpoint):
    """Send a tiny silent WAV to check if the endpoint supports MAI-Transcribe-2."""
    # Minimal valid WAV: 44-byte header + 1 sample of silence
    wav_header = (
        b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00'
        b'\x01\x00\x01\x00\x80\xbb\x00\x00\x00w\x01\x00'
        b'\x02\x00\x10\x00data\x02\x00\x00\x00\x00\x00'
    )
    definition = {
        'locales': ['nl'],
        'enhancedMode': {'enabled': True, 'model': 'MAI-Transcribe-2'},
    }
    url = _transcribe_url(endpoint)
    headers = {'Ocp-Apim-Subscription-Key': key}
    print(f'  Probing {url} …')
    files = {
        'audio': ('probe.wav', wav_header, 'audio/wav'),
        'definition': (None, json.dumps(definition), 'application/json'),
    }
    if _httpx is not None:
        with _httpx.Client(timeout=30) as client:
            resp_raw = client.post(url, headers=headers, files=files)
        status_code = resp_raw.status_code
        try:
            body = resp_raw.json()
        except Exception:
            body = resp_raw.text
    else:
        resp_raw = _requests.post(url, headers=headers, files=files, timeout=(30, 60))
        status_code = resp_raw.status_code
        try:
            body = resp_raw.json()
        except Exception:
            body = resp_raw.text

    print(f'  HTTP {status_code}')
    print(json.dumps(body, indent=2, ensure_ascii=False)[:800])
    if status_code in (200, 400):
        body_str = json.dumps(body) if isinstance(body, dict) else str(body)
        if 'Enhanced mode is currently not supported' in body_str:
            print('\n  Region does NOT support MAI-Transcribe-2.')
        else:
            print('\n  Endpoint is reachable and MAI-Transcribe-2 appears supported.')
    elif status_code == 401:
        print('\n  Authentication failed — check your key.')
    else:
        print('\n  Unexpected status — see response above.')


# ---------------------------------------------------------------------------
# Optional speaker identification (requires resemblyzer + stored profiles)
# ---------------------------------------------------------------------------

def _run_identification(ep_key: str, threshold: float = 0.75) -> None:
    """Run identify_speakers for ep_key if voice profiles are available."""
    profiles_dir = ROOT / 'data' / 'voice-profiles'
    if not profiles_dir.exists() or not any(profiles_dir.glob('*.npy')):
        print('  --identify: no profiles found in data/voice-profiles/; skipping.')
        return
    try:
        from scripts.identify_speakers import identify_episode  # type: ignore
    except ImportError:
        import importlib.util, sys as _sys
        spec = importlib.util.spec_from_file_location(
            'identify_speakers',
            pathlib.Path(__file__).parent / 'identify_speakers.py',
        )
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        identify_episode = mod.identify_episode
    print(f'  Running speaker identification for #{ep_key} …')
    identify_episode(ep_key, threshold=threshold, apply=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Transcribe podcast episodes via Azure MAI-Transcribe-2'
    )
    parser.add_argument('--episode', type=str, help='Episode number to transcribe')
    parser.add_argument('--all-missing', action='store_true',
                        help='Transcribe all episodes without a transcript')
    parser.add_argument('--probe', action='store_true',
                        help='Test endpoint connectivity and MAI-Transcribe-2 support')
    parser.add_argument('--key', help='Azure Speech API key')
    parser.add_argument('--endpoint',
                        help='Azure Speech endpoint, e.g. https://my-resource.cognitiveservices.azure.com/')
    parser.add_argument('--delete-mp3', action='store_true',
                        help='Delete the local MP3 after a successful transcription')
    parser.add_argument('--identify', action='store_true',
                        help='Run speaker identification against stored voice profiles after '
                             'transcription (requires pip install resemblyzer and profiles '
                             'built with build_voice_profiles.py)')
    args = parser.parse_args()

    if not args.episode and not args.all_missing and not args.probe:
        parser.error('Provide --episode N, --all-missing, or --probe')

    if _requests is None and _httpx is None:
        sys.exit('Neither requests nor httpx is installed. Run: pip install httpx requests')
    if _httpx is None:
        print('Warning: httpx not found, falling back to requests (may fail on large uploads on Windows).')
        print('         Install httpx: pip install httpx')

    # Use requests for downloads; httpx takes over for uploads
    http = _requests or _httpx
    key, endpoint = _load_credentials(args.key, args.endpoint)

    if not key:
        sys.exit('No Azure key found. Set AZURE_SPEECH_KEY or pass --key')
    if not endpoint:
        sys.exit('No endpoint found. Set AZURE_SPEECH_ENDPOINT or pass --endpoint')

    if args.probe:
        probe(key, endpoint)
        return

    data = json.loads(EPISODES_JSON.read_text(encoding='utf-8'))
    eps_by_key = {_ep_key(e): e for e in data['eps']}

    if args.episode:
        keys = [str(args.episode)]
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        keys = [k for k in eps_by_key if not (OUT_DIR / f'{k}.json').exists()]
        print(f'{len(keys)} episodes missing transcripts')

    for ep_key in keys:
        ep = eps_by_key.get(ep_key)
        if ep is None:
            print(f'  Episode {ep_key} not found in episodes.json')
            continue
        print(f'Transcribing #{ep.get("n", ep_key)} — {ep["t"][:60]}')
        try:
            transcript = transcribe_episode(ep, key, endpoint, http)
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            out_path = OUT_DIR / f'{ep_key}.json'
            out_path.write_text(
                json.dumps(transcript, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            print(f'  → {out_path.relative_to(ROOT)}  '
                  f'({len(transcript["segments"])} segments)')
            if args.identify:
                _run_identification(ep_key)
            if args.delete_mp3:
                _delete_mp3(ep_key)
        except RateLimitError as exc:
            print(f'  Rate limited. Waiting {exc.retry_after}s …')
            time.sleep(exc.retry_after)
            try:
                transcript = transcribe_episode(ep, key, endpoint, http)
                out_path = OUT_DIR / f'{ep_key}.json'
                out_path.write_text(
                    json.dumps(transcript, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
                print(f'  → {out_path.relative_to(ROOT)}  '
                      f'({len(transcript["segments"])} segments)')
                if args.identify:
                    _run_identification(ep_key)
                if args.delete_mp3:
                    _delete_mp3(ep_key)
            except Exception as exc2:
                print(f'  Failed after retry: {exc2}')
        except TranscriptionError as exc:
            print(f'  Error: {exc}')


if __name__ == '__main__':
    main()
