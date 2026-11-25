"""GUI workflow logic without model downloads or real audio devices."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gui-tools'))
from diarization_core import EditorSession, SAMPLING_RATE, audio_clip


class Encoder:
    def __init__(self, *embeddings):
        self.embeddings = iter(embeddings)

    def embed_utterance(self, wav):
        return np.array(next(self.embeddings), dtype=np.float32)


def preprocess(clip, source_sr):
    assert source_sr == SAMPLING_RATE
    return clip


class TestDiarizationEditor(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / '1.json'
        self.transcript = dict(
            episode=1, source=dict(audio='https://example.org/episode.mp3'),
            speakers=[dict(id='S1', name='Alice', role='host'),
                      dict(id='S2', name='Bob', role='guest')],
            segments=[dict(start=i, end=i + 1, speaker='S1' if i != 1 else 'S2',
                           text=f'Line {i}', extra='preserve me') for i in range(4)],
            custom=dict(keep=True))
        self.path.write_text(json.dumps(self.transcript), encoding='utf-8')
        self.session = EditorSession(self.path)
        self.addCleanup(self.session.close)
        self.audio = np.ones(4 * SAMPLING_RATE, dtype=np.float32)

    def test_fix_rebuilds_profiles_and_protects_anchors_without_saving(self):
        self.assertEqual(self.session.confirmed, set())
        self.session.confirmed.update([0, 1])
        original = self.path.read_bytes()
        rows, folder = self.session.fix(self.audio, Encoder([1, 0], [0, 1], [0, 1], [1, 0]), preprocess)
        self.assertEqual([s['speaker'] for s in self.session.transcript['segments']],
                         ['S1', 'S2', 'S2', 'S1'])
        self.assertEqual([row['index'] for row in rows], [2, 3])
        np.testing.assert_allclose(np.load(folder / 'profile-1.npy'), [1, 0])
        self.assertEqual(json.loads((folder / 'profiles.json').read_text())['S1']['confirmed_lines'], [1])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(self.session.dirty)
        # Fine-tune a proposal, trust it, and run FIX again with a fresh profile.
        self.session.assign(2, 'S1')
        self.session.confirmed.add(2)
        _, second = self.session.fix(self.audio, Encoder([1, 0], [1, 0], [0, 1], [0, 1]), preprocess)
        self.assertNotEqual(folder, second)
        self.assertEqual(self.session.transcript['segments'][2]['speaker'], 'S1')
        self.assertEqual(self.session.transcript['segments'][3]['speaker'], 'S2')

    def test_save_preserves_payload_and_exact_backup_and_rejects_external_edits(self):
        original = self.path.read_bytes()
        self.session.assign(2, 'S2')
        backup = self.session.save()
        self.assertEqual(backup.read_bytes(), original)
        expected = copy.deepcopy(self.transcript)
        expected['segments'][2]['speaker'] = 'S2'
        self.assertEqual(json.loads(self.path.read_text()), expected)
        self.assertFalse(self.session.dirty)
        self.path.write_text('{"external": true}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed on disk'):
            self.session.save()
        self.assertEqual(self.path.read_text(), '{"external": true}')

    def test_missing_examples_and_bad_anchor_abort_without_partial_changes(self):
        before = copy.deepcopy(self.session.transcript)
        with self.assertRaisesRegex(ValueError, 'at least two'):
            self.session.fix(self.audio, Encoder(), preprocess)
        self.session.confirmed.update([0, 1])
        with self.assertRaisesRegex(ValueError, 'confirmed line 2'):
            self.session.fix(self.audio, Encoder([1, 0], [0, 0]), preprocess)
        self.assertEqual(self.session.transcript, before)

    def test_low_scores_still_choose_highest_ties_and_bad_audio_stay_unchanged(self):
        self.session.confirmed.update([0, 1])
        self.session.transcript['segments'][3]['end'] = 99
        rows, _ = self.session.fix(self.audio, Encoder([1, 0, 0], [0, 1, 0], [.1, .2, 1]), preprocess)
        self.assertEqual(rows[0]['speaker'], 'S2')
        self.assertLess(rows[0]['similarity'], .85)
        self.assertEqual(rows[1]['status'], 'audio-error')
        self.assertEqual(rows[1]['speaker'], 'S1')
        rows, _ = self.session.fix(self.audio, Encoder([1, 0], [0, 1], [1, 1]), preprocess)
        self.assertEqual(rows[0]['status'], 'ambiguous')

    def test_add_speaker_and_cleanup_and_default_unchecked_on_reopen(self):
        speaker = self.session.add_speaker(' Carol ')
        self.assertEqual(self.session.add_speaker('carol'), speaker)
        self.session.assign(0, speaker)
        self.session.confirmed.add(0)
        self.session.save()
        other = EditorSession(self.path)
        self.addCleanup(other.close)
        self.assertEqual(other.confirmed, set())
        self.assertEqual(other.transcript['segments'][0]['speaker'], speaker)
        temporary = Path(self.session.temp.name)
        self.session.close()
        self.assertFalse(temporary.exists())

    def test_clip_rejects_bad_timing_and_crops_exact_samples(self):
        audio = np.arange(4 * SAMPLING_RATE)
        clip = audio_clip(audio, dict(start=.25, end=.5))
        self.assertEqual((clip[0], clip[-1]), (4000, 7999))
        for start, end in [(-1, 2), (1, 0), (0, 99), (float('nan'), 1), ('bad', 1)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                audio_clip(audio, dict(start=start, end=end))


if __name__ == '__main__':
    unittest.main()
