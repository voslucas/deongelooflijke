"""Reassign individual transcript segments to the episode's known voice profiles.

Run identify_speakers.py first so speakers[] maps IDs to the correct names.
This script changes only segments[].speaker; text, timing and names stay intact.
Usage:
    python scripts/reidentify_segments.py --episode 327
    python scripts/reidentify_segments.py --episode 327 --report review.json
    python scripts/reidentify_segments.py --episode 327 --apply
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
import pathlib
import shutil
import tempfile

import numpy as np

from identify_speakers import _get_encoder
from utils import ep_key
from voice_utils import SAMPLING_RATE, cosine, download_mp3, load_audio, load_profiles

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = ROOT / 'data' / 'transcripts'
MP3_DIR = ROOT / 'data' / 'mp3'
PROFILES_DIR = ROOT / 'data' / 'voice-profiles'


def episode_profiles(transcript, all_profiles):
    """Require a valid, distinct profile for every named episode participant."""
    speakers = transcript.get('speakers', [])
    ids = [s['id'] for s in speakers]
    names = [s['name'].casefold() for s in speakers]
    if len(speakers) < 2 or len(set(ids)) != len(ids) or len(set(names)) != len(names):
        raise ValueError('Need at least two speakers with unique IDs and names.')
    by_name = {name.casefold(): emb for name, emb in all_profiles.items()}
    missing = [s['name'] for s in speakers if s['name'].casefold() not in by_name]
    if missing:
        raise ValueError('Missing voice profiles for: ' + ', '.join(missing)
                         + '. Build them from correctly labelled audio first.')
    profiles = {s['id']: by_name[s['name'].casefold()] for s in speakers}
    shapes = {emb.shape for emb in profiles.values()}
    if len(shapes) != 1 or any(
        emb.ndim != 1 or not emb.size or not np.isfinite(emb).all()
        or np.linalg.norm(emb) == 0 for emb in profiles.values()
    ):
        raise ValueError('Voice profiles must be finite, nonzero vectors of equal size.')
    return profiles


def classify_segments(transcript, audio, profiles, encoder, preprocess_wav,
                      threshold=0.85, margin=0.0, min_seconds=0.0):
    """Return review rows without mutating the transcript. Scores are not probabilities."""
    if not math.isfinite(threshold) or not -1 <= threshold <= 1:
        raise ValueError('threshold must be between -1 and 1.')
    if not math.isfinite(margin) or not 0 <= margin <= 2:
        raise ValueError('margin must be between 0 and 2.')
    if not math.isfinite(min_seconds) or min_seconds < 0:
        raise ValueError('min_seconds must be nonnegative.')
    rows = []
    duration = len(audio) / SAMPLING_RATE
    segments = transcript.get('segments', [])
    for index, seg in enumerate(segments):
        if index % 50 == 0:
            print(f'  Checking segment {index + 1}/{len(segments)} ...', flush=True)
        row = dict(index=index, start=seg.get('start'), end=seg.get('end'),
                   text=seg.get('text', ''), original_speaker=seg.get('speaker'),
                   speaker=seg.get('speaker'), best_speaker=None, scores={},
                   similarity=None, margin=None, status='invalid-timing')
        rows.append(row)
        try:
            start, end = float(seg['start']), float(seg['end'])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(start) and math.isfinite(end)
                and 0 <= start < end <= duration):
            continue
        if end - start < min_seconds:
            row['status'] = 'short-audio'
            continue
        clip = audio[int(start * SAMPLING_RATE):int(end * SAMPLING_RATE)]
        if not len(clip):
            row['status'] = 'short-audio'
            continue
        wav = preprocess_wav(clip, source_sr=SAMPLING_RATE)
        if not len(wav) or len(wav) < min_seconds * SAMPLING_RATE:
            row['status'] = 'short-speech'
            continue
        emb = np.asarray(encoder.embed_utterance(wav))
        if (emb.shape != next(iter(profiles.values())).shape
                or not np.isfinite(emb).all() or np.linalg.norm(emb) == 0):
            row['status'] = 'invalid-embedding'
            continue
        scores = {sid: cosine(emb, profile) for sid, profile in profiles.items()}
        ranked = sorted(scores, key=scores.get, reverse=True)
        best, runner_up = ranked[:2]
        gap = scores[best] - scores[runner_up]
        row.update(scores=scores, best_speaker=best, similarity=scores[best], margin=gap)
        if scores[best] < threshold:
            row['status'] = 'low-similarity'
        elif gap <= 0 or gap < margin:
            row['status'] = 'ambiguous'
        else:
            row['speaker'] = best
            row['status'] = 'confirmed' if best == seg.get('speaker') else 'changed'
    return rows


def save_corrections(path, transcript, rows):
    """Back up the original bytes and atomically replace the transcript."""
    updated = dict(transcript)
    updated['segments'] = [dict(seg) for seg in transcript.get('segments', [])]
    for row in rows:
        if row['status'] == 'changed':
            updated['segments'][row['index']]['speaker'] = row['speaker']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = path.with_name(f'{path.name}.{stamp}.bak')
    shutil.copy2(path, backup)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         suffix='.tmp', delete=False) as handle:
            temporary = pathlib.Path(handle.name)
            json.dump(updated, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--episode', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Save segment changes with a backup')
    mode.add_argument('--dry-run', action='store_true', help='Preview only (default)')
    parser.add_argument('--threshold', type=float, default=0.85,
                        help='Minimum cosine similarity to accept the best match (default: 0.85)')
    parser.add_argument('--margin', type=float, default=0.0,
                        help='Optional minimum lead over the runner-up (default: 0)')
    parser.add_argument('--min-seconds', type=float, default=0.0,
                        help='Optional minimum audio and speech duration (default: 0, no cutoff)')
    parser.add_argument('--report', type=pathlib.Path, help='Write all per-line scores as JSON')
    args = parser.parse_args()
    path = TRANSCRIPTS_DIR / f'{args.episode}.json'
    if not path.is_file() or path.parent.resolve() != TRANSCRIPTS_DIR.resolve():
        parser.error(f'Transcript not found: {path}')
    if args.report and (args.report.resolve() == path.resolve()
                        or args.report.resolve().is_relative_to(PROFILES_DIR.resolve())
                        or args.report.resolve().is_relative_to(MP3_DIR.resolve())):
        parser.error('Report must not overwrite the transcript, audio or voice profiles.')
    transcript = json.loads(path.read_text(encoding='utf-8'))
    try:
        profiles = episode_profiles(transcript, load_profiles(PROFILES_DIR))
        # Validate settings before downloading audio or initializing the model.
        classify_segments({'segments': []}, np.array([]), profiles, None, None,
                          args.threshold, args.margin, args.min_seconds)
    except ValueError as exc:
        parser.error(str(exc))
    audio_path = MP3_DIR / f'{args.episode}.mp3'
    if not audio_path.exists():
        episodes = json.loads((ROOT / 'data' / 'episodes.json').read_text(encoding='utf-8'))
        episode = next((e for e in episodes['eps'] if ep_key(e) == args.episode), None)
        if not episode or not episode.get('mp3'):
            parser.error(f'No MP3 URL for episode {args.episode}')
        download_mp3(episode['mp3'], audio_path)
    print('  Loading audio ...', flush=True)
    audio = load_audio(audio_path)
    encoder, preprocess_wav = _get_encoder()
    rows = classify_segments(transcript, audio, profiles, encoder, preprocess_wav,
                             args.threshold, args.margin, args.min_seconds)
    names = {s['id']: s['name'] for s in transcript['speakers']}
    for row in rows:
        if row['status'] == 'changed':
            print(f"  #{row['index'] + 1} {row['start']:.2f}-{row['end']:.2f}s: "
                  f"{names.get(row['original_speaker'], row['original_speaker'])} -> "
                  f"{names[row['speaker']]} (sim={row['similarity']:.3f}, "
                  f"lead={row['margin']:.3f}) | {row['text'][:100]}")
    counts = Counter(row['status'] for row in rows)
    print('  Results: ' + ', '.join(f'{status}={n}' for status, n in sorted(counts.items())))
    if args.apply and counts['changed']:
        backup = save_corrections(path, transcript, rows)
        print(f"  Saved {counts['changed']} corrections. Backup: {backup}")
    elif not args.apply:
        print(f"  Dry-run: {counts['changed']} proposed changes. Re-run with --apply to save.")
    else:
        print('  No corrections to save.')
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(dict(
            episode=args.episode, applied=args.apply, speakers=transcript['speakers'],
            threshold=args.threshold, margin=args.margin, min_seconds=args.min_seconds,
            segments=rows), ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'  Review report: {args.report}')


if __name__ == '__main__':
    main()
