"""Build Resemblyzer voice-embedding profiles for known speakers.

Usage:
    python scripts/build_voice_profiles.py --episode 327
    python scripts/build_voice_profiles.py --episode 327 --speakers "David Boogerd"
    python scripts/build_voice_profiles.py --episode 327 --merge   # refine existing profiles

Reads data/transcripts/{N}.json to locate clean speaker segments, then loads
data/mp3/{N}.mp3 (downloading it if absent), encodes each speaker's audio with
Resemblyzer's VoiceEncoder, and saves the mean embedding to
data/voice-profiles/{slug}.npy.

The --merge flag blends new embeddings into existing profiles with equal weight
(simple running average over recorded episodes), allowing gradual refinement.

Dependencies:
    pip install resemblyzer
    resemblyzer pulls in numpy, librosa, webrtcvad automatically.
"""
import argparse, json, pathlib, sys, re
import numpy as np
from utils import slug as _slug, ep_key as _ep_key
from voice_utils import download_mp3 as _download_mp3, load_audio as _load_audio

ROOT         = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON = ROOT / 'data' / 'episodes.json'
TRANSCRIPTS_DIR = ROOT / 'data' / 'transcripts'
MP3_DIR      = ROOT / 'data' / 'mp3'
PROFILES_DIR = ROOT / 'data' / 'voice-profiles'

SAMPLING_RATE = 16_000      # Resemblyzer expects 16 kHz mono
MIN_SEG_SECS  = 3.0         # skip segments shorter than this
MAX_SEGS      = 20          # use at most this many segments per speaker (longest first)


def _build_profile(audio: np.ndarray, segments: list[dict]) -> np.ndarray | None:
    """Return mean Resemblyzer embedding for a list of {start, end} segments."""
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav
    except ImportError:
        sys.exit('resemblyzer not found. Install it: pip install resemblyzer')

    encoder = VoiceEncoder()

    # Pick the longest segments first, up to MAX_SEGS
    segs = [s for s in segments if (s['end'] - s['start']) >= MIN_SEG_SECS]
    segs.sort(key=lambda s: s['end'] - s['start'], reverse=True)
    segs = segs[:MAX_SEGS]

    if not segs:
        return None

    embeddings = []
    for seg in segs:
        start_i = int(seg['start'] * SAMPLING_RATE)
        end_i   = int(seg['end']   * SAMPLING_RATE)
        clip = audio[start_i:end_i]
        if len(clip) < SAMPLING_RATE:
            continue
        try:
            wav = preprocess_wav(clip, source_sr=SAMPLING_RATE)
            emb = encoder.embed_utterance(wav)
            embeddings.append(emb)
        except Exception as exc:
            print(f'    Skipping segment {seg["start"]:.1f}–{seg["end"]:.1f}: {exc}')

    if not embeddings:
        return None

    print(f'    Encoded {len(embeddings)} segments')
    return np.mean(embeddings, axis=0).astype(np.float32)


def build_profiles(ep_key: str, speakers_filter: list[str] | None, merge: bool) -> None:
    transcript_path = TRANSCRIPTS_DIR / f'{ep_key}.json'
    if not transcript_path.exists():
        sys.exit(f'Transcript not found: {transcript_path}')

    transcript = json.loads(transcript_path.read_text(encoding='utf-8'))

    # Group segments by speaker name
    id_to_name = {s['id']: s['name'] for s in transcript.get('speakers', [])}
    by_name: dict[str, list[dict]] = {}
    for seg in transcript.get('segments', []):
        name = id_to_name.get(seg['speaker'])
        if name:
            by_name.setdefault(name, []).append(seg)

    if speakers_filter:
        by_name = {k: v for k, v in by_name.items() if k in speakers_filter}

    if not by_name:
        sys.exit('No matching speakers found in transcript.')

    # Load audio (download if needed)
    mp3_path = MP3_DIR / f'{ep_key}.mp3'
    if not mp3_path.exists():
        eps_data = json.loads(EPISODES_JSON.read_text(encoding='utf-8'))
        ep = next((e for e in eps_data['eps'] if _ep_key(e) == ep_key), None)
        if not ep or not ep.get('mp3'):
            sys.exit(f'No mp3 URL for episode {ep_key}')
        _download_mp3(ep['mp3'], mp3_path)

    print(f'  Loading audio from {mp3_path.relative_to(ROOT)} …')
    audio = _load_audio(mp3_path)

    PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    for name, segs in by_name.items():
        slug = _slug(name)
        profile_path = PROFILES_DIR / f'{slug}.npy'
        print(f'  Building profile for {name} ({len(segs)} segments) …')

        new_emb = _build_profile(audio, segs)
        if new_emb is None:
            print(f'    Not enough clean audio for {name}, skipping.')
            continue

        if merge and profile_path.exists():
            existing = np.load(profile_path)
            # Simple running mean with equal weight
            merged = (existing + new_emb) / 2.0
            merged /= np.linalg.norm(merged)
            np.save(profile_path, merged.astype(np.float32))
            print(f'    Merged into {profile_path.relative_to(ROOT)}')
        else:
            norm = new_emb / np.linalg.norm(new_emb)
            np.save(profile_path, norm.astype(np.float32))
            print(f'    Saved {profile_path.relative_to(ROOT)}')


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Build Resemblyzer voice profiles from a correctly identified transcript'
    )
    parser.add_argument('--episode', required=True,
                        help='Episode number (must have a correct transcript)')
    parser.add_argument('--speakers',
                        help='Comma-separated speaker names to build profiles for '
                             '(default: all speakers in the transcript)')
    parser.add_argument('--merge', action='store_true',
                        help='Blend new embedding into existing profile (running average)')
    args = parser.parse_args()

    speakers_filter = [s.strip() for s in args.speakers.split(',')] if args.speakers else None
    build_profiles(args.episode, speakers_filter, args.merge)
    print('Done.')


if __name__ == '__main__':
    main()
