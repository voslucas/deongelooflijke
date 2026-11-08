"""Tests for scripts/4_split_data.py — episode splitting, keyword extraction, aggregates."""
import json, pathlib, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).parent / 'fixtures'
sys.path.insert(0, str(ROOT / 'scripts'))

import importlib

# Reload the module to run against fixture data, not production data
import types

# We import the module's functions directly (not calling main())
from importlib import import_module
sd = import_module('4_split_data')


SAMPLE_EP = json.loads((FIXTURES / 'sample_episode.json').read_text(encoding='utf-8'))


class TestEpKey(unittest.TestCase):
    def test_numbered_episode_key(self):
        self.assertEqual(sd.ep_key(SAMPLE_EP), '327')

    def test_unnamed_episode_key(self):
        ep = dict(SAMPLE_EP, n=None, id='xyz789')
        self.assertEqual(sd.ep_key(ep), 'xxyz789')

    def test_unnamed_episode_key_xprefix(self):
        ep = dict(SAMPLE_EP, n=None, id='abc123')
        self.assertEqual(sd.ep_key(ep), 'xabc123')


class TestTruncateXs(unittest.TestCase):
    def test_short_text_unchanged(self):
        s = 'Kort.'
        self.assertEqual(sd.truncate_xs(s), s)

    def test_long_text_at_word_boundary(self):
        words = 'word ' * 80  # 400 chars
        result = sd.truncate_xs(words)
        self.assertLessEqual(len(result), 320)
        # must not cut mid-word
        self.assertFalse(result.endswith(' word'[:3]))  # ends at a full word

    def test_xs_no_mid_word_cut(self):
        # 'abcdefghij' repeated to exceed 320 chars
        s = 'abcdefghij ' * 35  # 385 chars
        result = sd.truncate_xs(s)
        self.assertLessEqual(len(result), 320)
        # last char should be 'j' (end of a word), not 'a'-'i' (mid-word)
        self.assertEqual(result[-1], 'j')


class TestTfIdf(unittest.TestCase):
    def test_kw_field_is_list_of_strings(self):
        eps = [dict(SAMPLE_EP)]
        sd.compute_tfidf(eps)
        self.assertIn('_kw', eps[0])
        self.assertIsInstance(eps[0]['_kw'], list)
        self.assertTrue(all(isinstance(w, str) for w in eps[0]['_kw']))

    def test_kw_max_10_entries(self):
        eps = [dict(SAMPLE_EP)]
        sd.compute_tfidf(eps)
        self.assertLessEqual(len(eps[0]['_kw']), 10)

    def test_kw_excludes_stopwords(self):
        eps = [dict(SAMPLE_EP)]
        sd.compute_tfidf(eps)
        for w in eps[0]['_kw']:
            self.assertNotIn(w, sd.STOP)

    def test_kw_top_tfidf(self):
        # With 3 episodes: 'iran' in ep1+ep2 (df=2), log(3/2)>0; more freq in ep1 → higher score
        ep1 = dict(SAMPLE_EP, t='Kader Iran boek', x='Iran islamitisch boek Iran Iran')
        ep2 = dict(SAMPLE_EP, n=1, t='Iran andere', x='Iran andere inhoud')
        ep3 = dict(SAMPLE_EP, n=2, t='Geheel anders', x='Geheel andere inhoud')
        eps = [ep1, ep2, ep3]
        sd.compute_tfidf(eps)
        kw1 = eps[0]['_kw']
        self.assertTrue(len(kw1) > 0, 'No keywords computed for ep1')
        self.assertIn('iran', kw1[:5], "Expected 'iran' in top keywords for ep1")


class TestFullRun(unittest.TestCase):
    """Run split_data against a small synthetic dataset in a temp directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

        # Minimal episodes.json
        ep_a = dict(SAMPLE_EP)
        ep_b = dict(SAMPLE_EP, n=1, t='Andere', x='Andere tekst', id='oth', sl='1-andere',
                    g=[], p=False, q=[], r=[], sj=[], th=[], f='Gesprek', mp3='')
        ep_unnamed = dict(SAMPLE_EP, n=None, t='Speciale', x='Speciale aflevering',
                          id='spec1', sl='spec-1', g=[], p=False, q=[], r=[], sj=[],
                          th=[], f='Trailer', mp3='')
        (self.root / 'data').mkdir()
        (self.root / 'data' / 'episodes.json').write_text(
            json.dumps({'eps': [ep_a, ep_b, ep_unnamed], 'bios': {}, 'built': '2024-01-01'}),
            encoding='utf-8',
        )
        self.orig_root = sd.ROOT
        self.orig_ep = sd.EPISODES_JSON
        self.orig_out = sd.OUT_DIR
        self.orig_tx = sd.TRANSCRIPTS_DIR
        sd.ROOT = self.root
        sd.EPISODES_JSON = self.root / 'data' / 'episodes.json'
        sd.OUT_DIR = self.root / 'site' / 'dist' / 'data'
        sd.TRANSCRIPTS_DIR = self.root / 'data' / 'transcripts'

    def tearDown(self):
        sd.ROOT = self.orig_root
        sd.EPISODES_JSON = self.orig_ep
        sd.OUT_DIR = self.orig_out
        sd.TRANSCRIPTS_DIR = self.orig_tx
        self.tmp.cleanup()

    def _run(self):
        sd.main()

    def test_full_fields_in_episode_file(self):
        self._run()
        ep_file = self.root / 'site' / 'dist' / 'data' / 'episodes' / '327.json'
        self.assertTrue(ep_file.exists())
        data = json.loads(ep_file.read_text())
        for field in ('x', 'r', 'id', 'sl', 'q', 'mp3'):
            self.assertIn(field, data, f'Heavy field {field} missing from episode file')

    def test_kw_in_episode_file(self):
        self._run()
        ep_file = self.root / 'site' / 'dist' / 'data' / 'episodes' / '327.json'
        data = json.loads(ep_file.read_text())
        self.assertIn('kw', data)
        self.assertIsInstance(data['kw'], list)

    def test_unnamed_episode_key(self):
        self._run()
        ep_file = self.root / 'site' / 'dist' / 'data' / 'episodes' / 'xspec1.json'
        self.assertTrue(ep_file.exists(), 'File xspec1.json not found')

    def test_index_json_created(self):
        self._run()
        idx = self.root / 'site' / 'dist' / 'data' / 'index.json'
        self.assertTrue(idx.exists())
        keys = json.loads(idx.read_text())
        self.assertIn('327', keys)
        self.assertIn('1', keys)
        self.assertIn('xspec1', keys)

    def test_no_transcripts_produces_empty_aggregates(self):
        self._run()
        for name in ('speakers', 'books', 'places', 'people'):
            path = self.root / 'site' / 'dist' / 'data' / f'{name}.json'
            self.assertTrue(path.exists())
            data = json.loads(path.read_text())
            self.assertEqual(data, [], f'{name}.json should be [] without transcripts')


if __name__ == '__main__':
    unittest.main()
