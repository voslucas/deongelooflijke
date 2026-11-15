"""Match Azure diarization speaker clusters to known voice profiles.

Usage:
    python scripts/identify_speakers.py --episode 327          # dry-run, show confidence table
    python scripts/identify_speakers.py --episode 327 --apply  # update transcript in place
    python scripts/identify_speakers.py --episode 327 --threshold 0.80

Reads data/transcripts/{N}.json (segments with speaker IDs like S1, S2, …),
loads data/mp3/{N}.mp3, computes a Resemblyzer embedding per speaker cluster,
and compares each embedding against every stored profile in data/voice-profiles/.

A match is accepted when cosine similarity >= threshold (default 0.75).
On --apply the matched names are written directly into data/transcripts/{N}.json
so the transcript is always the single source of truth for speaker names.

Dependencies:
    pip install resemblyzer
"""
import argparse, json, pathlib, sys, re
import numpy as np

ROOT            = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON   = ROOT / 'data' / 'episodes.json'
TRANSCRIPTS_DIR = ROOT / 'data' / 'transcripts'
MP3_DIR         = ROOT / 'data' / 'mp3'
PROFILES_DIR    = ROOT / 'data' / 'voice-profiles'

SAMPLING_RATE   = 16_000
MIN_SEG_SECS    = 1.0
DEFAULT_THRESHOLD = 0.75


def _slug_to_name(slug: str) -> str:
    return slug.replace('-', ' ').title()


def _load_profiles() -> dict[str, np.ndarray]:
    """Return {speaker_name: embedding} for all stored profiles."""
    profiles = {}
    if not PROFILES_DIR.exists():
        return profiles
    for path in sorted(PROFILES_DIR.glob('*.npy')):
        name = _slug_to_name(path.stem)
        profiles[name] = np.load(path).astype(np.float32)
    return profiles


def _download_mp3(url: str, dest: pathlib.Path) -> None:
    try:
        import httpx as _http
        client_cls = _http.Client
        timeout = _http.Timeout(60, read=7200)
    except ImportError:
        import requests as _http  # type: ignore
        client_cls = None
        timeout = (60, 7200)

    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f'  Downloading {url} …')
    if client_cls:
        with client_cls(timeout=timeout) as client:
            resp = client.get(url, follow_redirects=True)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    else:
        resp = _http.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in resp.iter_content(65536):
                f.write(chunk)
    print(f'  Saved {dest.stat().st_size // 1_000_000} MB')


def _load_audio(mp3_path: pathlib.Path) -> np.ndarray:
    try:
        import librosa
    except ImportError:
        sys.exit('librosa not found. Install resemblyzer: pip install resemblyzer')
    audio, _ = librosa.load(str(mp3_path), sr=SAMPLING_RATE, mono=True)
    return audio.astype(np.float32)


def _embed_cluster(audio: np.ndarray, segs: list[dict]) -> np.ndarray | None:
    """Return mean embedding for a speaker cluster (list of {start, end} dicts)."""
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav
    except ImportError:
        sys.exit('resemblyzer not found. Install it: pip install resemblyzer')

    encoder = VoiceEncoder()
    segs = [s for s in segs if (s['end'] - s['start']) >= MIN_SEG_SECS]
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
            embeddings.append(encoder.embed_utterance(wav))
        except Exception:
            pass

    if not embeddings:
        return None
    emb = np.mean(embeddings, axis=0).astype(np.float32)
    return emb / np.linalg.norm(emb)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def identify_episode(ep_key: str, threshold: float, apply: bool) -> None:
    transcript_path = TRANSCRIPTS_DIR / f'{ep_key}.json'
    if not transcript_path.exists():
        sys.exit(f'Transcript not found: {transcript_path}')

    all_profiles = _load_profiles()
    if not all_profiles:
        sys.exit(f'No profiles found in {PROFILES_DIR}. Run build_voice_profiles.py first.')

    transcript = json.loads(transcript_path.read_text(encoding='utf-8'))
    speakers = transcript.get('speakers', [])

    # Only use profiles for speakers who are actually in this episode
    episode_names = {s['name'] for s in speakers}
    profiles = {name: emb for name, emb in all_profiles.items() if name in episode_names}

    # Group segments by speaker ID (S1, S2, …)
    by_sid: dict[str, list[dict]] = {s['id']: [] for s in speakers}
    for seg in transcript.get('segments', []):
        sid = seg.get('speaker')
        if sid in by_sid:
            by_sid[sid].append(seg)

    # Load audio (download if needed)
    mp3_path = MP3_DIR / f'{ep_key}.mp3'
    if not mp3_path.exists():
        eps_data = json.loads(EPISODES_JSON.read_text(encoding='utf-8'))
        ep = next((e for e in eps_data['eps']
                   if (str(e['n']) if e['n'] is not None else 'x' + e['id']) == ep_key), None)
        if not ep or not ep.get('mp3'):
            sys.exit(f'No mp3 URL for episode {ep_key}')
        _download_mp3(ep['mp3'], mp3_path)

    print(f'  Loading audio …')
    audio = _load_audio(mp3_path)

    # Compute embeddings per cluster
    cluster_embs: dict[str, np.ndarray | None] = {}
    for spk in speakers:
        sid = spk['id']
        segs = by_sid.get(sid, [])
        print(f'  Encoding {sid} ({spk["name"]}, {len(segs)} segments) …')
        cluster_embs[sid] = _embed_cluster(audio, segs)

    # 1-to-1 assignment: compare every cluster against every episode profile,
    # then greedily assign best-matching pairs (highest sim first) so that each
    # profile and each cluster is used at most once.  Unmatched clusters are
    # guests whose voice profile we don't have — shown as "leftover".
    sim_matrix: dict[tuple[str, str], float] = {}
    for spk in speakers:
        sid = spk['id']
        emb = cluster_embs.get(sid)
        if emb is None:
            continue
        for name, prof in profiles.items():
            sim_matrix[(sid, name)] = _cosine(emb, prof)

    assigned_sids:   set[str] = set()
    assigned_names:  set[str] = set()
    assignments: dict[str, tuple[str, float]] = {}  # sid -> (name, sim)

    for (sid, name), sim in sorted(sim_matrix.items(), key=lambda x: x[1], reverse=True):
        if sid in assigned_sids or name in assigned_names:
            continue
        if sim >= threshold:
            assignments[sid] = (name, sim)
            assigned_sids.add(sid)
            assigned_names.add(name)

    # Leftover assignment: if exactly one cluster has no profile match and exactly
    # one episode name has no profile, assign by elimination.
    unmatched_sids   = [s['id'] for s in speakers if s['id'] not in assigned_sids
                        and cluster_embs.get(s['id']) is not None]
    unmatched_names  = [s['name'] for s in speakers if s['name'] not in profiles]
    if len(unmatched_sids) == 1 and len(unmatched_names) == 1:
        assignments[unmatched_sids[0]] = (unmatched_names[0], float('nan'))

    print()
    print(f'  {"SID":<5} {"Current name":<20} {"Matched to":<20} {"Sim":>6}  {"Action"}')
    print(f'  {"-"*5} {"-"*20} {"-"*20} {"-"*6}  {"-"*20}')

    corrections: dict[str, str] = {}
    for spk in speakers:
        sid = spk['id']
        current_name = spk['name']
        emb = cluster_embs.get(sid)

        if emb is None:
            print(f'  {sid:<5} {current_name:<20} {"(no audio)":<20} {"":>6}')
            continue

        if sid not in assignments:
            print(f'  {sid:<5} {current_name:<20} {"(unresolved)":<20} {"":>6}  — ambiguous')
            continue

        matched_name, sim = assignments[sid]
        sim_str = f'{sim:>6.3f}' if sim == sim else '  —  '  # nan = by elimination
        by_elim = sim != sim

        if matched_name == current_name:
            tag = '≡ by elimination' if by_elim else '✓ confirmed'
            print(f'  {sid:<5} {current_name:<20} {matched_name:<20} {sim_str}  {tag}')
        else:
            tag = '✎ rename (by elimination)' if by_elim else f'✎ rename → {matched_name}'
            print(f'  {sid:<5} {current_name:<20} {matched_name:<20} {sim_str}  {tag}')
            corrections[sid] = matched_name

    if not corrections:
        print('\n  No confident matches above threshold. No changes.')
        return

    if not apply:
        print(f'\n  Dry-run: would apply {len(corrections)} correction(s) to '
              f'data/transcripts/{ep_key}.json')
        print('  Re-run with --apply to save.')
        return

    # Apply corrections directly to the transcript file
    for sid, new_name in corrections.items():
        for spk in transcript.get('speakers', []):
            if spk['id'] == sid:
                spk['name'] = new_name
                break
    transcript_path.write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'\n  Applied {len(corrections)} correction(s) to {transcript_path.relative_to(ROOT)}')


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Match speaker clusters to known voice profiles'
    )
    parser.add_argument('--episode', required=True, help='Episode number')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print results without writing corrections (default behaviour without --apply)')
    parser.add_argument('--apply', action='store_true',
                        help='Write corrections into the transcript file (default: dry-run)')
    parser.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD,
                        help=f'Minimum cosine similarity to accept a match '
                             f'(default: {DEFAULT_THRESHOLD})')
    args = parser.parse_args()
    identify_episode(args.episode, args.threshold, args.apply)


if __name__ == '__main__':
    main()
