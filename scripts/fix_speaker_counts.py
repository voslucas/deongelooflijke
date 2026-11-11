"""Fix transcripts that have more Azure speakers than actual participants.

Reads the expected speaker count from data/episodes.json (1 host + optional
Stefan Paas + guests), strips extra speakers from the transcript, and reassigns
their segments to the nearest preceding legitimate speaker.  No audio or API
calls are made.

Usage:
    python scripts/fix_speaker_counts.py               # dry-run: report only
    python scripts/fix_speaker_counts.py --apply       # write corrected files
    python scripts/fix_speaker_counts.py --episode 327 --apply
"""
import argparse, json, pathlib, sys

ROOT    = pathlib.Path(__file__).resolve().parent.parent
EPS     = ROOT / 'data' / 'episodes.json'
TR_DIR  = ROOT / 'data' / 'transcripts'


def _expected(ep: dict) -> int:
    return 1 + (1 if ep.get('p') else 0) + len(ep.get('g', []))


import re as _re
_GHOST_RE = _re.compile(r'^Spreker\s+\d+$')


def fix_transcript(tr: dict, expected: int) -> tuple[dict, bool]:
    """Return (fixed_transcript, was_changed).

    Removal priority: 'Spreker N' ghosts first (Azure diarization artefacts),
    then excess real-named speakers by word count rank if still over the cap.
    """
    speakers = tr.get('speakers', [])
    if len(speakers) <= expected:
        return tr, False

    # Count words per speaker ID in segments
    word_counts: dict[str, int] = {s['id']: 0 for s in speakers}
    for seg in tr.get('segments', []):
        sid = seg.get('speaker')
        if sid in word_counts:
            word_counts[sid] += len(seg.get('text', '').split())

    # Sort: ghosts last, then by ascending word count (remove smallest first)
    def removal_priority(s):
        is_ghost = bool(_GHOST_RE.match(s['name']))
        return (not is_ghost, word_counts.get(s['id'], 0))

    # Fixed speakers: keep the best `expected` after sorting by priority
    sorted_spk = sorted(speakers, key=removal_priority, reverse=True)
    keep_set = {s['id'] for s in sorted_spk[:expected]}
    extra_ids = {s['id'] for s in sorted_spk[expected:]}

    # Preserve original role order for the kept speakers list
    kept_speakers = [s for s in speakers if s['id'] in keep_set]
    # Build ordered list of valid speaker IDs for fallback lookup
    valid_ids = [s['id'] for s in kept_speakers]

    # Reassign extra-speaker segments to the most recent preceding valid speaker
    segments = tr.get('segments', [])
    last_valid = valid_ids[0]  # fallback: first speaker (David Boogerd)
    new_segments = []
    for seg in segments:
        sid = seg.get('speaker')
        if sid in keep_set:
            last_valid = sid
            new_segments.append(seg)
        elif sid in extra_ids:
            # Reassign to last seen valid speaker
            new_seg = dict(seg)
            new_seg['speaker'] = last_valid
            new_segments.append(new_seg)
        else:
            new_segments.append(seg)

    new_tr = dict(tr)
    new_tr['speakers'] = kept_speakers
    new_tr['segments'] = new_segments
    return new_tr, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true',
                        help='Write corrected files (default: dry-run)')
    parser.add_argument('--episode', type=str,
                        help='Fix a single episode number')
    args = parser.parse_args()

    eps_data = json.loads(EPS.read_text(encoding='utf-8'))
    ep_map = {e['n']: e for e in eps_data['eps']}

    if args.episode:
        paths = [TR_DIR / f'{args.episode}.json']
    else:
        paths = sorted(TR_DIR.glob('*.json'),
                       key=lambda p: int(p.stem) if p.stem.isdigit() else 0)

    changed = 0
    for p in paths:
        n = int(p.stem) if p.stem.isdigit() else None
        if n is None:
            continue
        ep = ep_map.get(n)
        if not ep:
            print(f'  #{n}: no episode data, skipping')
            continue

        tr = json.loads(p.read_text(encoding='utf-8'))
        exp = _expected(ep)
        actual = len(tr.get('speakers', []))
        if actual <= exp:
            continue

        fixed, was_changed = fix_transcript(tr, exp)
        kept_ids = {s['id'] for s in fixed['speakers']}
        extra_names = [s['name'] for s in tr['speakers'] if s['id'] not in kept_ids]
        print(f'  #{n}: {actual} -> {exp} speakers  (removed: {extra_names})', end='')

        if args.apply and was_changed:
            p.write_text(json.dumps(fixed, ensure_ascii=False, indent=2),
                         encoding='utf-8')
            print('  saved')
        else:
            print('  (dry-run)')
        changed += 1

    action = 'Fixed' if args.apply else 'Would fix'
    print(f'\n{action} {changed} transcript(s).')


if __name__ == '__main__':
    main()
