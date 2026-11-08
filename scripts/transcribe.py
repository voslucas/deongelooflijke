"""Transcribe a podcast episode via ElevenLabs Scribe v2 with speaker diarization.

Usage:
    python scripts/transcribe.py --episode N [--api-key KEY]
    python scripts/transcribe.py --all-missing [--api-key KEY]

Dependencies:
    pip install requests elevenlabs

API key is read from --api-key, then ELEVENLABS_API_KEY env var, then .env file.
Output: data/transcripts/{key}.json  (transcript-schema.md input shape)
        data/speaker-corrections/{key}.json  (speaker mapping for review/override)

Transcription strategy:
    1. Try source_url — ElevenLabs fetches the MP3 from NPO directly (no upload).
    2. If that fails, download the MP3 to data/mp3/{key}.mp3 and upload via the
       official elevenlabs SDK (avoids Windows SSL write-timeout with raw requests).
"""
import argparse, datetime, json, os, pathlib, re, sys, time, unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON = ROOT / 'data' / 'episodes.json'
CORRECTIONS_DIR = ROOT / 'data' / 'speaker-corrections'
OUT_DIR = ROOT / 'data' / 'transcripts'
MP3_DIR = ROOT / 'data' / 'mp3'

try:
    import requests as _requests
except ImportError:
    _requests = None

try:
    from elevenlabs.client import ElevenLabs as _ElevenLabs
except ImportError:
    _ElevenLabs = None


class RateLimitError(Exception):
    def __init__(self, retry_after=60):
        self.retry_after = retry_after
        super().__init__(f'Rate limited; retry after {retry_after}s')


class TranscriptionError(Exception):
    pass


def _load_api_key(explicit=None):
    if explicit:
        return explicit
    k = os.environ.get('ELEVENLABS_API_KEY')
    if k:
        return k
    env_file = ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            if line.startswith('ELEVENLABS_API_KEY='):
                return line.split('=', 1)[1].strip().strip('"\'')
    return None


def _ep_key(e):
    return str(e['n']) if e['n'] is not None else 'x' + e['id']


def _speaker_map(words, ep):
    """Map ElevenLabs speaker IDs to canonical names based on word count rank."""
    counts = {}
    for w in words:
        sid = w.get('speaker_id', '')
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    ranked = [sid for sid, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)]

    guests = ep.get('g', [])
    has_paas = ep.get('p', False)

    mapping = {}
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
    """Overlay any manual corrections from data/speaker-corrections/{key}.json."""
    path = CORRECTIONS_DIR / f'{key}.json'
    if path.exists():
        try:
            corrections = json.loads(path.read_text(encoding='utf-8'))
            for sid, name in corrections.items():
                if sid in mapping:
                    role = mapping[sid][1]
                    mapping[sid] = (name, role)
        except Exception as exc:
            print(f'  Warning: could not read corrections for {key}: {exc}')
    return mapping


def _words_to_transcript(words, mapping, ep):
    """Convert ElevenLabs word list to transcript-schema.md input shape."""
    # Build speakers list ordered by role
    seen = {}
    for _, (name, role) in mapping.items():
        if name not in seen:
            seen[name] = role
    role_order = {'Presentator': 0, 'Vaste gast': 1, 'Gast': 2}
    spk_list = sorted(seen.items(), key=lambda x: (role_order.get(x[1], 2), x[0]))
    name_to_id = {name: f'S{i+1}' for i, (name, _) in enumerate(spk_list)}
    speakers = [{'id': name_to_id[name], 'name': name, 'role': role}
                for name, role in spk_list]

    segments = []
    events = []
    cur_text = []
    cur_speaker = None
    cur_start = None
    cur_end = None

    def flush_seg():
        if cur_text and cur_speaker is not None:
            name = mapping.get(cur_speaker, (f'Unknown {cur_speaker}', 'Gast'))[0]
            sid = name_to_id.get(name, 'S1')
            segments.append({
                'start': round(cur_start, 3),
                'end': round(cur_end, 3),
                'speaker': sid,
                'text': ' '.join(cur_text),
            })

    for w in words:
        wtype = w.get('type', 'word')
        if wtype == 'spacing':
            continue
        if wtype == 'audio_event':
            evt = w.get('text', w.get('value', ''))
            t = round(w.get('start', 0), 3)
            if 'laughter' in evt.lower() or 'laugh' in evt.lower():
                name = mapping.get(cur_speaker or '', ('', ''))[0]
                sid = name_to_id.get(name, 'S1') if name else 'S1'
                events.append({'t': t, 'type': 'laugh', 'speaker': sid, 'size': 2})
            continue

        speaker_id = w.get('speaker_id', cur_speaker)
        # Detect speaker change → emit overlap event if rapid switch
        if cur_speaker and speaker_id != cur_speaker and cur_end is not None:
            gap = w.get('start', 0) - cur_end
            if gap < 0.3 and cur_text:
                name_a = mapping.get(cur_speaker, ('', ''))[0]
                name_b = mapping.get(speaker_id, ('', ''))[0]
                events.append({
                    't': round(cur_end, 3),
                    'type': 'overlap',
                    'speakers': [name_to_id.get(name_a, 'S1'), name_to_id.get(name_b, 'S1')],
                })
            flush_seg()
            cur_text = []
            cur_speaker = speaker_id
            cur_start = w.get('start', 0)
        elif cur_speaker is None:
            cur_speaker = speaker_id
            cur_start = w.get('start', 0)

        cur_text.append(w.get('text', '').strip())
        cur_end = w.get('end', w.get('start', 0))

    flush_seg()

    # Minimal summary / chapters / highlights / mentions / bible placeholders
    summary = {'tldr': '', 'points': []}
    chapters = []
    highlights = []
    mentions = []
    bible = []

    return {
        'episode': ep.get('n'),
        'source': {
            'audio': ep.get('mp3', ''),
            'model': 'elevenlabs/scribe-v2',
            'created': datetime.date.today().isoformat(),
        },
        'speakers': speakers,
        'segments': segments,
        'events': events,
        'summary': summary,
        'chapters': chapters,
        'highlights': highlights,
        'mentions': mentions,
        'bible': bible,
    }


def _download_mp3(mp3_url, dest_path, requests):
    """Download mp3_url to dest_path with a simple progress indicator."""
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
                print(f'\r  {pct}% ({done // 1_000_000} / {total // 1_000_000} MB)', end='', flush=True)
    print()
    print(f'  Saved to {dest_path.relative_to(ROOT)}  ({done // 1_000_000} MB)')


def _word_to_dict(w):
    """Normalise an SDK word object or plain dict to the shape _speaker_map expects."""
    if isinstance(w, dict):
        return w
    try:
        return w.model_dump()          # Pydantic v2 (elevenlabs ≥ 1.x)
    except AttributeError:
        pass
    try:
        return w.dict()                # Pydantic v1
    except AttributeError:
        pass
    return {k: getattr(w, k, None)
            for k in ('text', 'type', 'start', 'end', 'speaker_id', 'value')}


def transcribe_episode(ep, api_key):
    """Transcribe via ElevenLabs Scribe v2.

    Strategy:
      1. Try source_url — ElevenLabs fetches the MP3 from the CDN directly (no upload).
      2. If that returns a 4xx, download the MP3 to data/mp3/ and upload via the
         official elevenlabs SDK (avoids the Windows SSL write-timeout with raw requests).
    """
    if _requests is None:
        sys.exit('requests is not installed. Run: pip install requests elevenlabs')
    requests = _requests

    mp3_url = ep.get('mp3', '')
    if not mp3_url:
        raise TranscriptionError('No mp3 URL for this episode')

    key = _ep_key(ep)
    num_speakers = max(1, 1 + int(bool(ep.get('p'))) + len(ep.get('g', [])))
    headers = {'xi-api-key': api_key}
    base_form = {
        'model_id': 'scribe_v2',
        'diarize': 'true',
        'num_speakers': str(num_speakers),
        'language_code': 'nld',
        'tag_audio_events': 'true',
    }

    words = None

    # 1. source_url: ElevenLabs fetches the audio themselves — nothing to upload
    print('  Trying source_url (no upload) …')
    try:
        resp = requests.post(
            'https://api.elevenlabs.io/v1/speech-to-text',
            headers=headers,
            data={**base_form, 'source_url': mp3_url},
            timeout=(30, 3600),
        )
        if resp.ok:
            words = resp.json().get('words', [])
            print(f'  source_url succeeded ({len(words)} words)')
        elif resp.status_code == 429:
            raise RateLimitError(int(resp.headers.get('Retry-After', 60)))
        else:
            print(f'  source_url failed ({resp.status_code}): {resp.text[:120]}')
    except RateLimitError:
        raise
    except Exception as exc:
        print(f'  source_url request error: {exc}')

    # 2. File upload via official SDK (handles large uploads without SSL write timeout)
    if words is None:
        if _ElevenLabs is None:
            raise TranscriptionError('elevenlabs package not installed. Run: pip install elevenlabs')
        mp3_path = MP3_DIR / f'{key}.mp3'
        if mp3_path.exists():
            print(f'  Using cached MP3: {mp3_path.relative_to(ROOT)}')
        else:
            _download_mp3(mp3_url, mp3_path, requests)
        print(f'  Uploading via SDK ({mp3_path.stat().st_size // 1_000_000} MB) …')
        client = _ElevenLabs(api_key=api_key)
        with open(mp3_path, 'rb') as f:
            tx = client.speech_to_text.convert(
                file=f,
                model_id='scribe_v2',
                diarize=True,
                num_speakers=num_speakers,
                language_code='nld',
                tag_audio_events=True,
            )
        words = [_word_to_dict(w) for w in (tx.words or [])]
        print(f'  SDK upload succeeded ({len(words)} words)')

    # Map speaker IDs to names
    key = _ep_key(ep)
    mapping = _speaker_map(words, ep)
    mapping = _apply_corrections(mapping, key)

    # Save correction mapping for review
    CORRECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    correction_path = CORRECTIONS_DIR / f'{key}.json'
    if not correction_path.exists():
        correction_path.write_text(
            json.dumps({sid: name for sid, (name, _) in mapping.items()},
                       ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    return _words_to_transcript(words, mapping, ep)


def main():
    parser = argparse.ArgumentParser(description='Transcribe podcast episodes')
    parser.add_argument('--episode', type=str, help='Episode number to transcribe')
    parser.add_argument('--all-missing', action='store_true',
                        help='Transcribe all episodes without a transcript')
    parser.add_argument('--api-key', help='ElevenLabs API key')
    args = parser.parse_args()

    if not args.episode and not args.all_missing:
        parser.error('Provide --episode N or --all-missing')

    api_key = _load_api_key(args.api_key)
    if not api_key:
        sys.exit('No API key found. Set ELEVENLABS_API_KEY or pass --api-key')

    data = json.loads(EPISODES_JSON.read_text(encoding='utf-8'))
    eps_by_key = {_ep_key(e): e for e in data['eps']}

    if args.episode:
        keys = [str(args.episode)]
    else:
        # all episodes not yet transcribed
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        keys = [k for k in eps_by_key if not (OUT_DIR / f'{k}.json').exists()]
        print(f'{len(keys)} episodes missing transcripts')

    for key in keys:
        ep = eps_by_key.get(key)
        if ep is None:
            print(f'  Episode {key} not found in episodes.json')
            continue
        print(f'Transcribing #{ep.get("n", key)} — {ep["t"][:60]}')
        try:
            transcript = transcribe_episode(ep, api_key)
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            out_path = OUT_DIR / f'{key}.json'
            out_path.write_text(
                json.dumps(transcript, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            print(f'  → {out_path.relative_to(ROOT)}  '
                  f'({len(transcript["segments"])} segments, '
                  f'{len(transcript["events"])} events)')
        except RateLimitError as exc:
            print(f'  Rate limited. Waiting {exc.retry_after}s …')
            time.sleep(exc.retry_after)
            # retry once
            try:
                transcript = transcribe_episode(ep, api_key)
                out_path = OUT_DIR / f'{key}.json'
                out_path.write_text(
                    json.dumps(transcript, ensure_ascii=False, indent=2),
                    encoding='utf-8',
                )
            except Exception as exc2:
                print(f'  Failed after retry: {exc2}')
        except TranscriptionError as exc:
            print(f'  Error: {exc}')


if __name__ == '__main__':
    main()
