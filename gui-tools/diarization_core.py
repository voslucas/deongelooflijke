"""Testable session and temporary voice-profile logic for the Tk editor."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from reidentify_segments import save_corrections
from voice_utils import SAMPLING_RATE, cosine


def audio_clip(audio, segment):
    """Reject invalid intervals rather than silently clipping their boundaries."""
    try:
        start, end = float(segment['start']), float(segment['end'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Invalid segment timestamps.') from exc
    if not (math.isfinite(start) and math.isfinite(end)
            and 0 <= start < end <= len(audio) / SAMPLING_RATE):
        raise ValueError('Segment timestamps fall outside the episode audio.')
    clip = audio[int(start * SAMPLING_RATE):int(end * SAMPLING_RATE)]
    if not len(clip):
        raise ValueError('Segment contains no audio samples.')
    return clip


def valid_embedding(value):
    value = np.asarray(value, dtype=np.float32)
    if (value.ndim != 1 or not value.size or not np.isfinite(value).all()
            or np.linalg.norm(value) == 0):
        raise ValueError('Audio produced an unusable voice embedding.')
    return value / np.linalg.norm(value)


def fix_assignments(transcript, confirmed, audio, encoder, preprocess, profile_dir,
                    progress=lambda message: None):
    """Build profiles only from trusted lines; return proposals without mutation.

    Confirmed lines remain locked. Other usable lines get their highest cosine
    score (no minimum threshold); exact ties and unusable audio keep their label.
    """
    speakers = {speaker['id']: speaker['name'] for speaker in transcript['speakers']}
    groups = {}
    for index in sorted(confirmed):
        speaker = transcript['segments'][index]['speaker']
        groups.setdefault(speaker, []).append(index)
    if len(groups) < 2:
        raise ValueError('Mark correct examples for at least two different speakers first.')
    profiles = {}
    manifest = {}
    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    for number, (speaker, indices) in enumerate(groups.items()):
        progress(f'Voice profile: {speakers[speaker]}')
        embeddings = []
        for index in indices:
            try:
                wav = preprocess(audio_clip(audio, transcript['segments'][index]),
                                 source_sr=SAMPLING_RATE)
                if not len(wav):
                    raise ValueError('No speech remains after preprocessing.')
                embeddings.append(valid_embedding(encoder.embed_utterance(wav)))
            except Exception as exc:
                raise ValueError(f'Cannot use confirmed line {index + 1} '
                                 f'({speakers[speaker]}): {exc}') from exc
        profiles[speaker] = valid_embedding(np.mean(embeddings, axis=0))
        filename = f'profile-{number + 1}.npy'
        np.save(profile_dir / filename, profiles[speaker])
        manifest[speaker] = dict(name=speakers[speaker], file=filename,
                                 confirmed_lines=[i + 1 for i in indices])
    (profile_dir / 'profiles.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    # Only classify unlocked lines: human-verified anchors cannot be overwritten.
    indices = [i for i in range(len(transcript['segments'])) if i not in confirmed]
    rows = []
    for position, index in enumerate(indices):
        if position % 10 == 0:
            progress(f'Comparing line {position + 1}/{len(indices)}')
        segment = transcript['segments'][index]
        row = dict(speaker=segment['speaker'], status='audio-error', scores={})
        try:
            wav = preprocess(audio_clip(audio, segment), source_sr=SAMPLING_RATE)
            if not len(wav):
                raise ValueError('No speech remains after preprocessing.')
            embedding = valid_embedding(encoder.embed_utterance(wav))
            scores = {sid: cosine(embedding, profile) for sid, profile in profiles.items()}
            ranked = sorted(scores, key=scores.get, reverse=True)
            best, runner_up = ranked[:2]
            row.update(scores=scores, similarity=scores[best],
                       margin=scores[best] - scores[runner_up])
            if scores[best] == scores[runner_up]:
                row['status'] = 'ambiguous'
            else:
                row.update(speaker=best, status='confirmed' if best == segment['speaker'] else 'changed')
        except Exception as exc:
            row['error'] = str(exc)
        row['index'] = index
        rows.append(row)
    return rows


class EditorSession:
    def __init__(self, path):
        self.path = Path(path)
        self.original_bytes = self.path.read_bytes()
        self.transcript = json.loads(self.original_bytes.decode('utf-8-sig'))
        speakers = self.transcript.get('speakers', [])
        ids = [s['id'] for s in speakers]
        names = [s['name'].strip().casefold() for s in speakers]
        if not ids or len(set(ids)) != len(ids) or len(set(names)) != len(names) or '' in names:
            raise ValueError('Transcript needs unique speaker IDs and nonempty unique names.')
        if any(s.get('speaker') not in ids for s in self.transcript.get('segments', [])):
            raise ValueError('Transcript contains a line with an unknown speaker ID.')
        self.saved = deepcopy(self.transcript)
        self.confirmed = set()  # Deliberately false for every line on opening.
        self.reviews = {}
        self.temp = tempfile.TemporaryDirectory(prefix='diarization-editor-')
        self.round = 0

    @property
    def dirty(self):
        return self.transcript != self.saved

    def assign(self, index, speaker):
        if speaker not in {s['id'] for s in self.transcript['speakers']}:
            raise ValueError('Unknown speaker.')
        self.transcript['segments'][index]['speaker'] = speaker
        self.reviews.pop(index, None)

    def add_speaker(self, name):
        name = name.strip()
        if not name:
            raise ValueError('Enter a speaker name.')
        for speaker in self.transcript['speakers']:
            if speaker['name'].casefold() == name.casefold():
                return speaker['id']
        number = 1
        ids = {s['id'] for s in self.transcript['speakers']}
        while f'S{number}' in ids:
            number += 1
        speaker = f'S{number}'
        self.transcript['speakers'].append(dict(id=speaker, name=name, role='guest'))
        return speaker

    def fix(self, audio, encoder, preprocess, progress=lambda message: None):
        self.round += 1
        folder = Path(self.temp.name) / f'round-{self.round}'
        rows = fix_assignments(self.transcript, self.confirmed, audio, encoder,
                               preprocess, folder, progress)
        # Commit to memory only once the whole operation succeeds.
        for row in rows:
            self.transcript['segments'][row['index']]['speaker'] = row['speaker']
        self.reviews = {row['index']: row for row in rows}
        return rows, folder

    def save(self):
        if self.path.read_bytes() != self.original_bytes:
            raise ValueError('Transcript changed on disk. Reopen the episode before saving '
                             'to avoid overwriting another process\'s changes.')
        backup = save_corrections(self.path, self.transcript, [])
        self.original_bytes = self.path.read_bytes()
        self.saved = deepcopy(self.transcript)
        return backup

    def close(self):
        self.temp.cleanup()
