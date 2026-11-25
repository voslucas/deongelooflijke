"""Per-line voice reassignment, confidence guards and transcript preservation."""
import copy
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import reidentify_segments as rs


class FakeEncoder:
    def __init__(self, *embeddings):
        self.embeddings = iter(embeddings)

    def embed_utterance(self, wav):
        return np.array(next(self.embeddings), dtype=np.float32)


class TestReidentifySegments(unittest.TestCase):
    def setUp(self):
        self.transcript = {
            'episode': 1, 'source': {'model': 'test'},
            'speakers': [{'id': 'S1', 'name': 'Alice', 'role': 'host'},
                         {'id': 'S2', 'name': 'Bob', 'role': 'guest'},
                         {'id': 'S3', 'name': 'Carol', 'role': 'guest'}],
            'segments': [dict(start=0, end=2, speaker='S1', text='Hello', extra=1),
                         dict(start=2, end=4, speaker='S1', text='Again')],
            'events': [],
        }
        self.profiles = dict(zip(('S1', 'S2', 'S3'), np.eye(3, dtype=np.float32)))
        self.audio = np.ones(4 * rs.SAMPLING_RATE, dtype=np.float32)

    def classify(self, *embeddings, transcript=None, preprocess=None, **options):
        return rs.classify_segments(
            self.transcript if transcript is None else transcript, self.audio,
            self.profiles, FakeEncoder(*embeddings),
            preprocess or (lambda clip, source_sr: clip), **options)

    def test_independent_lines_can_both_change_to_same_speaker(self):
        original = copy.deepcopy(self.transcript)
        rows = self.classify([0, 1, 0], [0, 1, 0])
        self.assertEqual([r['speaker'] for r in rows], ['S2', 'S2'])
        self.assertTrue(all(r['status'] == 'changed' for r in rows))
        self.assertEqual(self.transcript, original)
        self.assertEqual(set(rows[0]['scores']), set(self.profiles))

    def test_low_similarity_and_ambiguous_lines_keep_original(self):
        rows = self.classify([1, 1, 1], [0.70, 0.71, 0], threshold=0.70, margin=0.05)
        self.assertEqual([r['status'] for r in rows], ['low-similarity', 'ambiguous'])
        self.assertEqual([r['speaker'] for r in rows], ['S1', 'S1'])

    def test_ties_remain_ambiguous_even_with_zero_margin(self):
        rows = self.classify([1, 1, 0], [1, 1, 0], threshold=0.5, margin=0)
        self.assertTrue(all(r['status'] == 'ambiguous' for r in rows))

    def test_short_silent_and_invalid_intervals_not_encoded(self):
        transcript = dict(segments=[
            dict(start=0, end=0.2, speaker='S1'),
            dict(start=-1, end=2, speaker='S1'),
            dict(start=3, end=5, speaker='S1'),
            dict(start='bad', end=2, speaker='S1'),
            dict(start=0, end=2, speaker='S1'),
        ])
        rows = self.classify(transcript=transcript,
                             preprocess=lambda clip, source_sr: np.array([]), min_seconds=1)
        self.assertEqual([r['status'] for r in rows], [
            'short-audio', 'invalid-timing', 'invalid-timing',
            'invalid-timing', 'short-speech'])

    def test_audio_crops_use_exact_segment_bounds(self):
        seen = []
        audio = np.arange(4 * rs.SAMPLING_RATE, dtype=np.float32)

        def preprocess(clip, source_sr):
            seen.append((clip[0], clip[-1], source_sr))
            return clip

        rs.classify_segments(self.transcript, audio, self.profiles,
                             FakeEncoder([1, 0, 0], [0, 0, 1]), preprocess)
        self.assertEqual(seen, [(0, 31999, 16000), (32000, 63999, 16000)])

    def test_missing_or_invalid_profiles_fail_before_classification(self):
        with self.assertRaisesRegex(ValueError, 'Carol'):
            rs.episode_profiles(self.transcript, {'Alice': np.ones(3), 'Bob': np.ones(3)})
        with self.assertRaisesRegex(ValueError, 'nonzero'):
            rs.episode_profiles(self.transcript, dict(Alice=np.zeros(3),
                                                      Bob=np.ones(3), Carol=np.ones(3)))
        profiles = rs.episode_profiles(self.transcript, dict(
            alice=np.ones(3), BOB=np.ones(3), Carol=np.ones(3), Outsider=np.ones(3)))
        self.assertEqual(set(profiles), {'S1', 'S2', 'S3'})

    def test_invalid_embedding_retains_original(self):
        rows = self.classify([0, 0, 0], [float('nan'), 1, 0])
        self.assertTrue(all(r['status'] == 'invalid-embedding' for r in rows))

    def test_apply_preserves_everything_except_segment_speaker_and_backs_up_bytes(self):
        rows = self.classify([0, 1, 0], [1, 0, 0])
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / '1.json'
            original = json.dumps(self.transcript).encode('utf-8')
            path.write_bytes(original)
            backup = rs.save_corrections(path, self.transcript, rows)
            self.assertEqual(backup.read_bytes(), original)
            expected = copy.deepcopy(self.transcript)
            expected['segments'][0]['speaker'] = 'S2'
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')), expected)
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_invalid_settings_rejected(self):
        for options in [dict(threshold=2), dict(margin=-1), dict(min_seconds=-1),
                        dict(threshold=float('nan'))]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.classify(**options)

    def test_short_lines_use_highest_score_with_default_threshold(self):
        transcript = dict(segments=[dict(start=0, end=0.2, speaker='S1'),
                                    dict(start=0.2, end=0.4, speaker='S1')])
        # A close runner-up does not block the winner; a score below .85 does.
        self.profiles = {
            'S1': np.array([0.849, np.sqrt(1 - 0.849 ** 2), 0]),
            'S2': np.array([0.85, np.sqrt(1 - 0.85 ** 2), 0]),
            'S3': np.array([0, 0, 1]),
        }
        rows = self.classify([1, 0, 0], [0.99, 0, -0.1], transcript=transcript)
        self.assertEqual(rows[0]['status'], 'changed')
        self.assertEqual(rows[0]['speaker'], 'S2')
        self.assertAlmostEqual(rows[0]['similarity'], 0.85)
        self.assertEqual(rows[1]['status'], 'low-similarity')
        self.assertEqual(rows[1]['speaker'], 'S1')

    def test_empty_speech_keeps_original_without_duration_cutoff(self):
        rows = self.classify(preprocess=lambda clip, source_sr: np.array([]))
        self.assertTrue(all(r['status'] == 'short-speech' for r in rows))

    def test_cli_dry_run_and_apply_with_report(self):
        for apply in (False, True):
            with self.subTest(apply=apply), tempfile.TemporaryDirectory() as directory:
                folder = pathlib.Path(directory)
                path = folder / '1.json'
                original = json.dumps(self.transcript).encode('utf-8')
                path.write_bytes(original)
                (folder / '1.mp3').touch()
                report = folder / 'review.json'
                args = ['reidentify_segments.py', '--episode', '1', '--report', str(report)]
                args.append('--apply' if apply else '--dry-run')
                with (patch.object(rs, 'TRANSCRIPTS_DIR', folder),
                      patch.object(rs, 'MP3_DIR', folder / 'mp3'),
                      patch.object(rs, 'load_profiles', return_value=dict(
                          Alice=self.profiles['S1'], Bob=self.profiles['S2'],
                          Carol=self.profiles['S3'])),
                      patch.object(rs, 'download_mp3'),
                      patch.object(rs, 'load_audio', return_value=self.audio),
                      patch.object(rs, '_get_encoder', return_value=(
                          FakeEncoder([0, 1, 0], [1, 0, 0]),
                          lambda clip, source_sr: clip)),
                      patch.object(sys, 'argv', args)):
                    # Keep cached audio in a separate directory, like production.
                    (folder / 'mp3').mkdir()
                    (folder / 'mp3' / '1.mp3').touch()
                    rs.main()
                self.assertEqual(json.loads(report.read_text())['applied'], apply)
                self.assertEqual(len(list(folder.glob('*.bak'))), int(apply))
                if apply:
                    self.assertEqual(json.loads(path.read_text())['segments'][0]['speaker'], 'S2')
                else:
                    self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
