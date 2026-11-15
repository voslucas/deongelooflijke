"""Iteratively bootstrap voice profiles from all transcribed episodes.

Each round finds episodes where exactly one speaker has no voice profile.
That speaker is identified by elimination, speaker corrections are written,
and a new profile is saved — expanding the pool for the next round.

Dry-run (default) simulates all rounds instantly using transcript data alone
(no audio downloaded).  Pass --apply to actually download MP3s, run Resemblyzer,
write corrections and profiles.

Episodes where 2+ speakers lack profiles are printed as needing manual
verification.

Usage:
    python scripts/bootstrap_profiles.py              # preview plan
    python scripts/bootstrap_profiles.py --apply      # run everything
    python scripts/bootstrap_profiles.py --apply --max-rounds 3
    python scripts/bootstrap_profiles.py --apply --threshold 0.80
"""
import argparse, json, pathlib, re, sys
import numpy as np

ROOT            = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON   = ROOT / 'data' / 'episodes.json'
TRANSCRIPTS_DIR = ROOT / 'data' / 'transcripts'
MP3_DIR         = ROOT / 'data' / 'mp3'
PROFILES_DIR    = ROOT / 'data' / 'voice-profiles'

SAMPLING_RATE     = 16_000
MIN_SEG_SECS      = 1.0
MAX_SEGS          = 20
DEFAULT_THRESHOLD = 0.75


# ---------------------------------------------------------------------------
# Shared helpers (mirror identify_speakers.py / build_voice_profiles.py)
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def _name_from_slug(slug: str) -> str:
    return slug.replace('-', ' ').title()


def _load_profiles() -> dict[str, np.ndarray]:
    profiles: dict[str, np.ndarray] = {}
    if not PROFILES_DIR.exists():
        return profiles
    for path in sorted(PROFILES_DIR.glob('*.npy')):
        profiles[_name_from_slug(path.stem)] = np.load(path).astype(np.float32)
    return profiles


def _download_mp3(url: str, dest: pathlib.Path) -> None:
    try:
        import httpx as _http
        client_cls = _http.Client
        timeout    = _http.Timeout(60, read=7200)
    except ImportError:
        import requests as _http  # type: ignore
        client_cls = None
        timeout    = (60, 7200)
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f'      Downloading {dest.name} …', flush=True)
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
    print(f'      Saved {dest.stat().st_size // 1_000_000} MB', flush=True)


def _load_audio(mp3_path: pathlib.Path) -> np.ndarray:
    import librosa
    audio, _ = librosa.load(str(mp3_path), sr=SAMPLING_RATE, mono=True)
    return audio.astype(np.float32)


def _embed_cluster(audio: np.ndarray, segs: list[dict],
                   encoder, preprocess_wav) -> np.ndarray | None:
    segs = [s for s in segs if (s['end'] - s['start']) >= MIN_SEG_SECS]
    segs.sort(key=lambda s: s['end'] - s['start'], reverse=True)
    segs = segs[:MAX_SEGS]
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


def _greedy_assign(cluster_embs: dict[str, np.ndarray | None],
                   ep_profiles: dict[str, np.ndarray],
                   speakers: list[dict],
                   threshold: float) -> dict[str, tuple[str, float]]:
    """1-to-1 greedy assignment + leftover-by-elimination."""
    sim_matrix: dict[tuple[str, str], float] = {}
    for spk in speakers:
        emb = cluster_embs.get(spk['id'])
        if emb is None:
            continue
        for name, prof in ep_profiles.items():
            sim_matrix[(spk['id'], name)] = _cosine(emb, prof)

    assigned_sids:  set[str] = set()
    assigned_names: set[str] = set()
    assignments: dict[str, tuple[str, float]] = {}

    for (sid, name), sim in sorted(sim_matrix.items(), key=lambda x: x[1], reverse=True):
        if sid in assigned_sids or name in assigned_names:
            continue
        if sim >= threshold:
            assignments[sid] = (name, sim)
            assigned_sids.add(sid)
            assigned_names.add(name)

    # Leftover by elimination
    unmatched_sids  = [s['id'] for s in speakers
                       if s['id'] not in assigned_sids
                       and cluster_embs.get(s['id']) is not None]
    unmatched_names = [s['name'] for s in speakers if s['name'] not in ep_profiles]
    if len(unmatched_sids) == 1 and len(unmatched_names) == 1:
        assignments[unmatched_sids[0]] = (unmatched_names[0], float('nan'))

    return assignments


# ---------------------------------------------------------------------------
# Round planning (works without audio)
# ---------------------------------------------------------------------------

def _plan_round(transcripts: dict[str, dict],
                profiles: set[str],
                skip: set[str]) -> tuple[list, list, list]:
    """Return (processable, needs_manual, fully_known) for the current profile set."""
    processable:  list[tuple[str, dict, str]]        = []  # (key, transcript, new_speaker)
    needs_manual: list[tuple[str, dict, list[str]]]  = []  # (key, transcript, unknowns)
    fully_known:  list[str]                           = []

    for ep_key in sorted(transcripts):
        if ep_key in skip:
            continue
        speakers = transcripts[ep_key].get('speakers', [])
        if not speakers:
            continue
        ep_names = [s['name'] for s in speakers]
        unknown  = [n for n in ep_names if n not in profiles]
        if len(unknown) == 0:
            fully_known.append(ep_key)
        elif len(unknown) == 1:
            processable.append((ep_key, transcripts[ep_key], unknown[0]))
        else:
            needs_manual.append((ep_key, transcripts[ep_key], unknown))

    return processable, needs_manual, fully_known


# ---------------------------------------------------------------------------
# Apply: process one episode (download audio, embed, write corrections+profile)
# ---------------------------------------------------------------------------

def _process_episode(ep_key: str, ep_url: str | None,
                     transcript: dict, known_new_speaker: str | None,
                     threshold: float) -> bool:
    """
    Identify all speakers, write corrections if needed, save profile for the
    new speaker.  Returns True on success.
    """
    speakers = transcript.get('speakers', [])

    mp3_path = MP3_DIR / f'{ep_key}.mp3'
    if not mp3_path.exists():
        if not ep_url:
            print(f'      No MP3 URL — skipping', flush=True)
            return False
        _download_mp3(ep_url, mp3_path)

    try:
        from resemblyzer import VoiceEncoder, preprocess_wav
    except ImportError:
        sys.exit('resemblyzer not found: pip install resemblyzer webrtcvad-wheels')

    print(f'      Loading audio …', flush=True)
    audio   = _load_audio(mp3_path)
    encoder = VoiceEncoder()

    by_sid: dict[str, list[dict]] = {s['id']: [] for s in speakers}
    for seg in transcript.get('segments', []):
        sid = seg.get('speaker')
        if sid in by_sid:
            by_sid[sid].append(seg)

    profiles   = _load_profiles()
    ep_names   = {s['name'] for s in speakers}
    ep_profiles = {n: e for n, e in profiles.items() if n in ep_names}

    cluster_embs: dict[str, np.ndarray | None] = {}
    for spk in speakers:
        sid = spk['id']
        print(f'      Encoding {sid} ({spk["name"]}, {len(by_sid[sid])} segs) …',
              flush=True)
        cluster_embs[sid] = _embed_cluster(audio, by_sid[sid], encoder, preprocess_wav)

    assignments = _greedy_assign(cluster_embs, ep_profiles, speakers, threshold)

    # Corrections
    corrections: dict[str, str] = {}
    new_speaker_sid: str | None = None

    for spk in speakers:
        sid     = spk['id']
        current = spk['name']
        if sid not in assignments:
            print(f'      {sid} ({current}): unresolved — manual check needed', flush=True)
            continue
        matched, sim = assignments[sid]
        sim_str = f'{sim:.3f}' if sim == sim else 'elim'
        tag = '✓' if matched == current else f'→ {matched}'
        print(f'      {sid} ({current}): {tag}  [{sim_str}]', flush=True)
        if matched != current:
            corrections[sid] = matched
        if matched == known_new_speaker and sim != sim:  # nan = by elimination
            new_speaker_sid = sid

    if corrections:
        transcript_path = TRANSCRIPTS_DIR / f'{ep_key}.json'
        for spk in transcript['speakers']:
            if spk['id'] in corrections:
                spk['name'] = corrections[spk['id']]
        transcript_path.write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        print(f'      Corrected transcript → {transcript_path.name}', flush=True)

    # Profile for new speaker (only when there is exactly one unknown)
    if known_new_speaker is None:
        return True  # corrections written; profile building deferred to manual step

    profile_path = PROFILES_DIR / f'{_slug(known_new_speaker)}.npy'
    if profile_path.exists():
        print(f'      Profile for {known_new_speaker} already exists — skipping build',
              flush=True)
        return True

    if new_speaker_sid is None:
        # Try to find the sid from assignments
        for spk in speakers:
            sid = spk['id']
            matched_name = (assignments.get(sid) or (None, None))[0]
            if matched_name == known_new_speaker:
                new_speaker_sid = sid
                break

    if new_speaker_sid is None:
        print(f'      Could not locate {known_new_speaker} cluster — no profile built',
              flush=True)
        return False

    emb = _embed_cluster(audio, by_sid.get(new_speaker_sid, []), encoder, preprocess_wav)
    if emb is None:
        print(f'      Not enough audio for {known_new_speaker} — no profile built',
              flush=True)
        return False

    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    np.save(profile_path, emb)
    print(f'      Profile saved → {profile_path.name}', flush=True)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Iteratively bootstrap voice profiles from transcribed episodes'
    )
    parser.add_argument('--apply', action='store_true',
                        help='Download audio, run Resemblyzer, write corrections + profiles '
                             '(default: dry-run / plan only)')
    parser.add_argument('--max-rounds', type=int, default=30,
                        help='Maximum number of iteration rounds (default: 30)')
    parser.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD,
                        help=f'Cosine similarity threshold (default: {DEFAULT_THRESHOLD})')
    args = parser.parse_args()

    # Load episode index for MP3 URLs
    eps_data = json.loads(EPISODES_JSON.read_text(encoding='utf-8'))
    ep_url_map: dict[str, str] = {
        (str(e['n']) if e.get('n') is not None else 'x' + e['id']): e['mp3']
        for e in eps_data.get('eps', [])
        if e.get('mp3')
    }

    # Load all transcripts
    transcripts: dict[str, dict] = {}
    for path in sorted(TRANSCRIPTS_DIR.glob('*.json')):
        try:
            transcripts[path.stem] = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            pass

    mode = 'APPLY' if args.apply else 'DRY-RUN (plan only — use --apply to run)'
    print(f'bootstrap_profiles — {mode}')
    print(f'Transcripts: {len(transcripts)}  |  threshold: {args.threshold}')
    print()

    skip: set[str]              = set()   # fully resolved — never re-evaluate
    corrections_done: set[str]  = set()   # 2+-unknown episodes with corrections written
    sim_profiles: set[str]      = set(_load_profiles())
    total_new: list[str]        = []

    for round_num in range(1, args.max_rounds + 1):
        processable, needs_manual, fully_known = _plan_round(
            transcripts, sim_profiles, skip
        )
        skip.update(fully_known)

        if not processable and not needs_manual:
            if round_num == 1:
                print('Nothing to process — all episodes fully identified.')
            else:
                print(f'Round {round_num}: nothing left to process.')
            break

        print(f'Round {round_num}')
        print(f'  Processable : {len(processable)} episode(s)  (1 unknown — by elimination)')
        print(f'  Needs manual: {len(needs_manual)} episode(s)  (2+ unknowns)')
        print()

        new_this_round: list[str] = []

        # --- 1-unknown episodes: full treatment ---
        for ep_key, transcript, new_speaker in processable:
            speakers     = transcript.get('speakers', [])
            ep_names     = [s['name'] for s in speakers]
            known        = [n for n in ep_names if n in sim_profiles]
            profile_path = PROFILES_DIR / f'{_slug(new_speaker)}.npy'
            already      = profile_path.exists()

            tag = '(profile exists)' if already else '(new)'
            print(f'  ep {ep_key:>5}  {len(speakers)} spk: '
                  f'{", ".join(known)} + [{new_speaker}] {tag}')

            if args.apply:
                ok = _process_episode(
                    ep_key, ep_url_map.get(ep_key),
                    transcript, new_speaker, args.threshold,
                )
                if ok and not already:
                    new_this_round.append(new_speaker)
                print()
            else:
                action = 'skip profile (exists)' if already else 'build profile'
                print(f'         → corrections if needed + {action}')

            skip.add(ep_key)
            sim_profiles.add(new_speaker)

        # --- 2+-unknown episodes: correct known speakers, flag unknowns ---
        new_manual = [(k, t, u) for k, t, u in needs_manual if k not in corrections_done]
        if new_manual:
            print(f'  Correcting known speakers in {len(new_manual)} '
                  f'partially-identified episode(s):')
            for ep_key, transcript, unknowns in new_manual:
                speakers = transcript.get('speakers', [])
                ep_names = [s['name'] for s in speakers]
                known    = [n for n in ep_names if n in sim_profiles]
                print(f'  ep {ep_key:>5}  {len(speakers)} spk: '
                      f'{", ".join(known)} confirmed | '
                      f'[{", ".join(unknowns)}] need manual verification')
                if args.apply:
                    _process_episode(
                        ep_key, ep_url_map.get(ep_key),
                        transcript, None, args.threshold,
                    )
                    print()
                else:
                    print(f'         → corrections for {", ".join(known)}; '
                          f'{len(unknowns)} unknown(s) remain')
                corrections_done.add(ep_key)

        if new_this_round:
            total_new.extend(new_this_round)
            print(f'\n  Built {len(new_this_round)} new profile(s): '
                  f'{", ".join(new_this_round)}')

        if not processable:
            # No new profiles built this round — further rounds won't help
            print(f'Round {round_num + 1}: no new profiles added, stopping.')
            break

        print()

    # Summary
    if args.apply and total_new:
        print(f'Total new profiles built: {len(total_new)}')
        for n in total_new:
            print(f'  + {n}')
        print()

    # Final manual verification list — episodes with 2+ unknowns that remain
    final_profiles = set(_load_profiles()) if args.apply else sim_profiles
    manual_final: list[tuple[str, list[str]]] = []
    for ep_key, transcript in sorted(transcripts.items()):
        if ep_key in skip:
            continue
        speakers = transcript.get('speakers', [])
        if not speakers:
            continue
        ep_names = [s['name'] for s in speakers]
        unknown  = [n for n in ep_names if n not in final_profiles]
        if len(unknown) >= 2:
            manual_final.append((ep_key, unknown))

    if manual_final:
        print(f'Episodes still needing manual verification ({len(manual_final)}):')
        print(f'  (known speakers already corrected; only the unknowns below remain)')
        print()
        for ep_key, unknown in manual_final:
            print(f'  ep {ep_key:>5}  unresolved: {", ".join(unknown)}')
        print()
        print('Per episode:')
        print('  python scripts/identify_speakers.py --episode <N> --dry-run')
        print('  python scripts/identify_speakers.py --episode <N> --apply')
        print('  python scripts/build_voice_profiles.py --episode <N> --speakers "<Name>"')
    else:
        print('All episodes fully identified.')


if __name__ == '__main__':
    main()
