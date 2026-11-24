"""Transcribe episodes with ElevenLabs Scribe v3 into the MAI transcript schema.

    python scripts/transcribe.py --episode 331
    python scripts/transcribe.py --all-missing --identify --delete-mp3
    python scripts/transcribe.py --episode x5005 --output data/transcription-tests/x5005.scribe-v3.json

Credentials: --key (or --api-key), ELEVENLABS_API_KEY, then .env.
Existing output files are always skipped. See docs/transcription-scribe.md.
"""
import argparse
import io
import json
import math
import os
import pathlib
import sys
import tempfile
import time
import wave

import httpx

import transcribe_azure as mai
from utils import ep_key

ROOT = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON = ROOT / 'data' / 'episodes.json'
OUT_DIR = ROOT / 'data' / 'transcripts'
MP3_DIR = mai.MP3_DIR
ENDPOINT = 'https://api.elevenlabs.io'
MODEL = 'scribe_v3'


def _load_api_key(explicit=None):
    key = explicit or os.environ.get('ELEVENLABS_API_KEY')
    env_file = ROOT / '.env'
    if not key and env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            name, sep, value = line.strip().partition('=')
            if sep and name.strip() == 'ELEVENLABS_API_KEY':
                return value.strip().strip('\"\'')
    return key


def _expected_speakers(ep):
    count = 1 + int(bool(ep.get('p'))) + len(ep.get('g', []))
    if not 1 <= count <= 32:
        raise mai.TranscriptionError(f'Expected speaker count {count} is outside Scribe\'s 1–32 range')
    return count


def _request(client, key, endpoint, count, *, audio, filename='audio.wav', content_type='audio/wav'):
    fields = {
        'model_id': MODEL, 'language_code': 'nl', 'diarize': 'true',
        'num_speakers': str(count), 'timestamps_granularity': 'word',
        'tag_audio_events': 'false', 'no_verbatim': 'false',
    }
    files = {name: (None, value) for name, value in fields.items()}
    files['file'] = (filename, audio, content_type)
    response = client.post(endpoint.rstrip('/') + '/v1/speech-to-text',
                           headers={'xi-api-key': key}, files=files)
    if response.status_code == 429:
        try:
            delay = max(0, int(response.headers.get('Retry-After', '60')))
        except ValueError:
            delay = 60
        raise mai.RateLimitError(delay)
    if response.status_code >= 400:
        raise mai.TranscriptionError(f'ElevenLabs API error {response.status_code}: {response.text[:500]}')
    try:
        data = response.json()
    except ValueError as exc:
        raise mai.TranscriptionError('ElevenLabs returned invalid JSON') from exc
    if not isinstance(data, dict) or not isinstance(data.get('words'), list):
        raise mai.TranscriptionError('ElevenLabs response has no timestamped words')
    return data


def _words_to_transcript(data, ep):
    """Group words by speaker, sentence, pause or 20s, then reuse MAI's schema.

    Spaces/events do not count towards speaker ranking. Unknown clusters retain
    their own labels rather than being silently attributed to the presenter.
    """
    phrases = []
    current = None
    for word in data['words']:
        if word.get('type', 'word') != 'word' or not word.get('text', '').strip():
            continue
        start, end = word.get('start'), word.get('end')
        if (not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start):
            raise mai.TranscriptionError('Invalid or missing word timestamps')
        speaker = word.get('speaker_id')
        text = word['text'].strip()
        previous_end = (current['offsetMilliseconds'] + current['durationMilliseconds']) / 1000 if current else 0
        if (current is None or speaker != current['speaker'] or start - previous_end > 1
                or start - current['offsetMilliseconds'] / 1000 >= 20
                or current['text'].endswith(('.', '?', '!'))):
            current = {'speaker': speaker, 'text': '', 'words': [],
                       'offsetMilliseconds': start * 1000, 'durationMilliseconds': 0}
            phrases.append(current)
        separator = '' if not current['text'] or text[0] in ',.;:!?…' else ' '
        current['text'] += separator + text
        current['words'].append(word)
        current['durationMilliseconds'] = max(previous_end if len(current['words']) > 1 else end, end) * 1000 - current['offsetMilliseconds']
    if not phrases:
        raise mai.TranscriptionError('No speech words returned; no transcript saved')
    mapping = mai._speaker_map(phrases, ep)
    detected = {phrase['speaker'] for phrase in phrases if phrase['speaker'] is not None}
    expected = _expected_speakers(ep)
    if len(detected) > expected:
        print(f'  Warning: Scribe returned {len(detected)} speaker clusters despite '
              f'num_speakers={expected}; excess clusters retain generic labels.', flush=True)
    for phrase in phrases:
        speaker = phrase['speaker']
        if speaker not in mapping:
            mapping[speaker] = (f'Spreker {speaker if speaker is not None else "onbekend"}', 'Gast')
    transcript = mai._azure_to_transcript({'phrases': phrases}, mapping, ep, include_events=False)
    transcript['source']['model'] = 'elevenlabs/' + MODEL
    return mai._apply_corrections(transcript, ep_key(ep))


def _download_mp3(client, url, path):
    """Stream into a temporary file so failed downloads never become cache hits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    print(f'  Downloading MP3 to {path}', flush=True)
    try:
        with client.stream('GET', url, follow_redirects=True,
                           timeout=httpx.Timeout(30, read=600)) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.part', delete=False) as output:
                temporary = pathlib.Path(output.name)
                for chunk in response.iter_bytes(65536):
                    output.write(chunk)
            if not temporary.stat().st_size:
                raise mai.TranscriptionError('Downloaded MP3 is empty')
            temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def transcribe_episode(ep, key, endpoint=ENDPOINT, client=None):
    if not ep.get('mp3'):
        raise mai.TranscriptionError('No mp3 URL for this episode')
    if client is None:
        with httpx.Client(timeout=httpx.Timeout(60, read=7200)) as http:
            return transcribe_episode(ep, key, endpoint, http)
    count = _expected_speakers(ep)
    print(f'  Scribe v3 | nl | verbatim | word timestamps | expected speakers: {count}', flush=True)
    mp3_path = MP3_DIR / f'{ep_key(ep)}.mp3'
    if mp3_path.exists() and mp3_path.stat().st_size:
        print(f'  Using cached MP3: {mp3_path}', flush=True)
    else:
        _download_mp3(client, ep['mp3'], mp3_path)
    print(f'  Uploading {mp3_path.stat().st_size / 1_000_000:.1f} MB to Scribe v3', flush=True)
    with mp3_path.open('rb') as audio:
        data = _request(client, key, endpoint, count, audio=audio,
                        filename=mp3_path.name, content_type='audio/mpeg')
    return _words_to_transcript(data, ep)


def _save_new(path, transcript):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects existing transcripts, including concurrent runs.
    with path.open('x', encoding='utf-8') as output:
        json.dump(transcript, output, ensure_ascii=False, indent=2)
        output.write('\n')


def _identify(key, path):
    profiles = ROOT / 'data' / 'voice-profiles'
    if not any(profiles.glob('*.npy')):
        print('  --identify: no voice profiles found; skipping.')
        return
    from identify_speakers import identify_episode
    identify_episode(key, threshold=0.75, apply=True, transcript_path=path)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Transcribe episodes via ElevenLabs Scribe v3')
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--episode', help='Episode number or unnumbered key, e.g. x5005')
    selection.add_argument('--all-missing', action='store_true')
    selection.add_argument('--probe', action='store_true', help='Test API with one second of silent audio')
    parser.add_argument('--key', '--api-key', dest='key', help='ElevenLabs API key')
    parser.add_argument('--endpoint', default=ENDPOINT, help='ElevenLabs API base URL')
    parser.add_argument('--delete-mp3', action='store_true', help='Delete cached MP3 after success')
    parser.add_argument('--identify', action='store_true', help='Identify speakers using stored voice profiles')
    output = parser.add_mutually_exclusive_group()
    output.add_argument('--output', type=pathlib.Path, help='New output file (requires --episode)')
    output.add_argument('--output-dir', type=pathlib.Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    if args.output and not args.episode:
        parser.error('--output requires --episode')
    key = _load_api_key(args.key)
    if not key:
        parser.error('Set ELEVENLABS_API_KEY in the environment/.env, or pass --key')
    failures = 0
    with httpx.Client(timeout=httpx.Timeout(60, read=7200)) as client:
        if args.probe:
            audio = io.BytesIO()
            with wave.open(audio, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b'\0' * 32000)
            audio.seek(0)
            _request(client, key, args.endpoint, 2, audio=audio)
            print('Scribe v3 accepted Dutch, verbatim, word timestamps and speaker-count settings.')
            return 0
        episodes = json.loads(EPISODES_JSON.read_text(encoding='utf-8'))['eps']
        by_key = {ep_key(ep): ep for ep in episodes}
        if args.episode and args.episode not in by_key:
            parser.error(
                f'Episode {args.episode} not found in data/episodes.json. '
                'After 1_parse_feed.py, run these metadata steps before transcription:\n'
                '  python scripts/2_extract_guests.py\n'
                '  python scripts/3_build_episode_data.py\n'
                'They supply the episode and expected speaker count used by Scribe.')
        keys = [args.episode] if args.episode else list(by_key)
        for episode_key in keys:
            path = args.output or args.output_dir / f'{episode_key}.json'
            if path.exists():
                if args.episode:
                    print(f'Skipping existing transcript: {path}')
                continue
            print(f'Transcribing {episode_key}: {by_key[episode_key]["t"]}', flush=True)
            try:
                for attempt in range(2):
                    try:
                        transcript = transcribe_episode(by_key[episode_key], key, args.endpoint, client)
                        break
                    except mai.RateLimitError as exc:
                        if attempt:
                            raise
                        print(f'  Rate limited; retrying in {exc.retry_after}s', flush=True)
                        time.sleep(exc.retry_after)
                _save_new(path, transcript)
                print(f'  Saved {path} ({len(transcript["segments"])} segments)', flush=True)
                if args.identify:
                    _identify(episode_key, path)
                if args.delete_mp3:
                    mai._delete_mp3(episode_key)
            except (mai.TranscriptionError, mai.RateLimitError, httpx.HTTPError, OSError) as exc:
                failures += 1
                print(f'  Failed: {exc}', file=sys.stderr)
    return int(bool(failures))


if __name__ == '__main__':
    sys.exit(main())
