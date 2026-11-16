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
from utils import slug as _slug, name_from_slug as _slug_to_name
from voice_utils import (download_mp3 as _download_mp3, load_audio as _load_audio,
                         load_profiles as _load_profiles_base, cosine as _cosine,
                         embed_cluster as _embed_cluster)

ROOT            = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON   = ROOT / 'data' / 'episodes.json'
TRANSCRIPTS_DIR = ROOT / 'data' / 'transcripts'
MP3_DIR         = ROOT / 'data' / 'mp3'
PROFILES_DIR    = ROOT / 'data' / 'voice-profiles'

SAMPLING_RATE   = 16_000
MIN_SEG_SECS    = 1.0
DEFAULT_THRESHOLD = 0.75


def _get_encoder():
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav
    except ImportError:
        sys.exit('resemblyzer not found. Install it: pip install resemblyzer')
    return VoiceEncoder(), preprocess_wav


def _load_profiles() -> dict[str, np.ndarray]:
    return _load_profiles_base(PROFILES_DIR)


def identify_episode(ep_key: str, threshold: float, apply: bool) -> None:
    transcript_path = TRANSCRIPTS_DIR / f'{ep_key}.json'
    if not transcript_path.exists():
        sys.exit(f'Transcript not found: {transcript_path}')

    all_profiles = _load_profiles()
    if not all_profiles:
        sys.exit(f'No profiles found in {PROFILES_DIR}. Run build_voice_profiles.py first.')

    transcript = json.loads(transcript_path.read_text(encoding='utf-8'))
    speakers = transcript.get('speakers', [])

    # Only use profiles for speakers who are actually in this episode.
    # Match case-insensitively; key on the transcript's version of the name.
    ep_name_map = {s['name'].lower(): s['name'] for s in speakers}
    profiles = {
        ep_name_map[name.lower()]: emb
        for name, emb in all_profiles.items()
        if name.lower() in ep_name_map
    }

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
    encoder, preprocess_wav = _get_encoder()

    # Compute embeddings per cluster
    cluster_embs: dict[str, np.ndarray | None] = {}
    for spk in speakers:
        sid = spk['id']
        segs = by_sid.get(sid, [])
        print(f'  Encoding {sid} ({spk["name"]}, {len(segs)} segments) …')
        cluster_embs[sid] = _embed_cluster(audio, segs, encoder, preprocess_wav)

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

    # Unified post-greedy resolution:
    # A certain elimination requires ALL other speakers to be voice-confirmed —
    # i.e. exactly 1 unresolved SID and exactly 1 unassigned cast name remain.
    # Any other situation means at least one unverified original label is being
    # relied on, which is not safe.  Displaced SIDs (whose label was claimed by a
    # voice assignment) still get a forced rename to keep names unique, but those
    # assignments are marked uncertain and never trigger a profile save.
    assigned_names_set = {name for _, (name, _) in assignments.items()}
    episode_cast       = {s['name'] for s in speakers}
    unresolved_all     = [s for s in speakers
                          if s['id'] not in assignments
                          and cluster_embs.get(s['id']) is not None]
    unassigned_all     = [n for n in episode_cast if n not in assigned_names_set]

    uncertain_sids: set[str] = set()

    if len(unresolved_all) == 1 and len(unassigned_all) == 1:
        # All other speakers confirmed by voice — this last pairing is certain.
        assignments[unresolved_all[0]['id']] = (unassigned_all[0], float('nan'))
    elif unresolved_all:
        # Multiple unknowns remain.  Only rename SIDs whose current label was
        # already claimed by a voice assignment (prevents duplicate names);
        # all such renames are uncertain — no profile is saved.
        displaced    = [s for s in unresolved_all if s['name'] in assigned_names_set]
        held_by_safe = {s['name'] for s in unresolved_all
                        if s['name'] not in assigned_names_set}
        available    = sorted(episode_cast - assigned_names_set - held_by_safe)
        for spk, name in zip(displaced, available):
            assignments[spk['id']] = (name, float('nan'))
            uncertain_sids.add(spk['id'])

    print()
    print(f'  {"SID":<5} {"Current name":<20} {"Matched to":<20} {"Sim":>6}  {"Action"}')
    print(f'  {"-"*5} {"-"*20} {"-"*20} {"-"*6}  {"-"*20}')

    corrections: dict[str, str] = {}
    elimination: dict[str, str] = {}  # sid -> name, assigned by certain elimination only
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
        uncertain = sid in uncertain_sids

        if by_elim and not uncertain:
            elimination[sid] = matched_name

        if matched_name == current_name:
            if uncertain:
                tag = '≡ forced (uncertain, no profile)'
            elif by_elim:
                tag = '≡ by elimination'
            else:
                tag = '✓ confirmed'
            print(f'  {sid:<5} {current_name:<20} {matched_name:<20} {sim_str}  {tag}')
        else:
            if uncertain:
                tag = '✎ rename (forced, uncertain — no profile)'
            elif by_elim:
                tag = '✎ rename (by elimination)'
            else:
                tag = f'✎ rename → {matched_name}'
            print(f'  {sid:<5} {current_name:<20} {matched_name:<20} {sim_str}  {tag}')
            corrections[sid] = matched_name

    # Determine which certain-elimination speakers need a profile built.
    # Uncertain forced reassignments are excluded — their identity is not confirmed.
    new_profiles: list[tuple[str, str]] = [
        (sid, name) for sid, name in elimination.items()
        if not (PROFILES_DIR / f'{_slug(name)}.npy').exists()
    ]
    if new_profiles and not apply:
        names = ', '.join(name for _, name in new_profiles)
        print(f'\n  Would also save voice profile(s) for: {names}')

    if not corrections and not new_profiles:
        print('\n  No corrections needed and all profiles already exist.')
        return

    if not apply:
        changes = len(corrections)
        print(f'\n  Dry-run: would apply {changes} correction(s) to '
              f'data/transcripts/{ep_key}.json')
        print('  Re-run with --apply to save.')
        return

    # Apply name corrections to the transcript
    if corrections:
        for sid, new_name in corrections.items():
            for spk in transcript.get('speakers', []):
                if spk['id'] == sid:
                    spk['name'] = new_name
                    break
        transcript_path.write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        print(f'\n  Applied {len(corrections)} correction(s) to '
              f'{transcript_path.relative_to(ROOT)}')

    # Save voice profiles for elimination-certain speakers
    for sid, name in new_profiles:
        emb = cluster_embs.get(sid)
        if emb is None:
            print(f'  No audio for {name} — profile skipped')
            continue
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        profile_path = PROFILES_DIR / f'{_slug(name)}.npy'
        np.save(profile_path, emb)
        print(f'  Saved voice profile → {profile_path.name}')


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
