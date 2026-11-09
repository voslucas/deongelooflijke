"""Transcribe a podcast episode via Microsoft MAI-Transcribe-2 with speaker diarization.

Usage:
    python scripts/transcribe_azure.py --episode N [--key KEY] [--endpoint URL]
    python scripts/transcribe_azure.py --all-missing [--key KEY] [--endpoint URL]
    python scripts/transcribe_azure.py --probe               # test region support

Credentials are read from --key/--endpoint, then AZURE_SPEECH_KEY / AZURE_SPEECH_ENDPOINT
env vars, then .env file.

Output: data/transcripts/{key}.json  (transcript-schema.md input shape)
        data/speaker-corrections/{key}.json  (speaker mapping for review/override)

API:
    POST https://{resource}.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15
    multipart/form-data  (audio + definition)
    Auth: Ocp-Apim-Subscription-Key header
    Limits: ≤ 2 hours, ≤ 250 MB per request
"""
import argparse, datetime, json, os, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON = ROOT / 'data' / 'episodes.json'
CORRECTIONS_DIR = ROOT / 'data' / 'speaker-corrections'
OUT_DIR = ROOT / 'data' / 'transcripts'
MP3_DIR = ROOT / 'data' / 'mp3'

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


# ---------------------------------------------------------------------------
# Episode helpers (same as transcribe.py)
# ---------------------------------------------------------------------------

def _ep_key(e):
    return str(e['n']) if e['n'] is not None else 'x' + e['id']


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
    """Map Azure speaker integers to canonical names by word-count rank."""
    counts: dict[int, int] = {}
    for ph in phrases:
        sid = ph.get('speaker')
        if sid is not None:
            counts[sid] = counts.get(sid, 0) + len(ph.get('words', [ph]))
    ranked = [sid for sid, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)]

    guests = ep.get('g', [])
    has_paas = ep.get('p', False)

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


def _apply_corrections(mapping, key):
    path = CORRECTIONS_DIR / f'{key}.json'
    if path.exists():
        try:
            corrections = json.loads(path.read_text(encoding='utf-8'))
            for sid_str, name in corrections.items():
                try:
                    sid = int(sid_str)
                except ValueError:
                    continue  # skip ElevenLabs-format string IDs
                if sid in mapping:
                    role = mapping[sid][1]
                    mapping[sid] = (name, role)
        except Exception as exc:
            print(f'  Warning: could not read corrections for {key}: {exc}')
    return mapping


# ---------------------------------------------------------------------------
# Convert Azure response → transcript-schema.md
# ---------------------------------------------------------------------------

def _azure_to_transcript(response_json, mapping, ep):
    phrases = response_json.get('phrases', [])

    # Build speakers list
    seen: dict[str, str] = {}
    for _, (name, role) in mapping.items():
        if name not in seen:
            seen[name] = role
    role_order = {'Presentator': 0, 'Vaste gast': 1, 'Gast': 2}
    spk_list = sorted(seen.items(), key=lambda x: (role_order.get(x[1], 2), x[0]))
    name_to_id = {name: f'S{i + 1}' for i, (name, _) in enumerate(spk_list)}
    speakers = [{'id': name_to_id[name], 'name': name, 'role': role}
                for name, role in spk_list]

    segments = []
    events = []
    prev_speaker = None
    prev_end_ms = None

    for ph in phrases:
        azure_sid = ph.get('speaker')
        name, _ = mapping.get(azure_sid, (f'Spreker {azure_sid}', 'Gast'))
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
    print(f'  Uploading {mb} MB to MAI-Transcribe-2 …')

    with open(mp3_path, 'rb') as audio_f:
        # httpx avoids the Windows SSLWantWriteError on large HTTPS uploads
        if _httpx is not None:
            with _httpx.Client(timeout=_httpx.Timeout(60, read=7200)) as client:
                resp_raw = client.post(
                    url,
                    headers=headers,
                    files={
                        'audio': (mp3_path.name, audio_f, 'audio/mpeg'),
                        'definition': (None, json.dumps(definition), 'application/json'),
                    },
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
                headers=headers,
                files={
                    'audio': (mp3_path.name, audio_f, 'audio/mpeg'),
                    'definition': (None, json.dumps(definition), 'application/json'),
                },
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
    mapping = _apply_corrections(mapping, ep_key)

    # Save correction template for review
    CORRECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    correction_path = CORRECTIONS_DIR / f'{ep_key}.json'
    if not correction_path.exists():
        correction_path.write_text(
            json.dumps({str(sid): name for sid, (name, _) in mapping.items()},
                       ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    return _azure_to_transcript(data, mapping, ep)


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
                if args.delete_mp3:
                    _delete_mp3(ep_key)
            except Exception as exc2:
                print(f'  Failed after retry: {exc2}')
        except TranscriptionError as exc:
            print(f'  Error: {exc}')


if __name__ == '__main__':
    main()
