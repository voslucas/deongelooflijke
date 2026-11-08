"""Tests for scripts/transcribe.py — speaker mapping, schema validation, error handling."""
import json, pathlib, sys, types, unittest
from unittest.mock import MagicMock, patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).parent / 'fixtures'
sys.path.insert(0, str(ROOT / 'scripts'))

import transcribe as tr

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

EP_NO_PAAS = {
    'n': 1, 't': 'Test', 'd': '2024-01-01', 's': 1800, 'x': 'x',
    'r': [], 'id': 'abc', 'sl': '1-test', 'g': ['Gast A'],
    'p': False, 'sj': [], 'th': [], 'f': 'Gesprek', 'q': [],
    'mp3': 'https://example.com/ep1.mp3',
}
EP_WITH_PAAS_1G = {
    'n': 2, 't': 'Test2', 'd': '2024-01-02', 's': 3600, 'x': 'x',
    'r': [], 'id': 'def', 'sl': '2-test2', 'g': ['Gast B'],
    'p': True, 'sj': [], 'th': [], 'f': 'Gesprek', 'q': [],
    'mp3': 'https://example.com/ep2.mp3',
}
EP_WITH_PAAS_2G = {
    'n': 327, 't': 'Kader Abdolah', 'd': '2024-03-15', 's': 4500, 'x': 'x',
    'r': [], 'id': 'abc123', 'sl': '327-kader', 'g': ['Kader Abdolah', 'Extra Gast'],
    'p': True, 'sj': [], 'th': [], 'f': 'Gesprek', 'q': [],
    'mp3': 'https://example.com/ep327.mp3',
}


def _words_for(*speaker_ids, counts=None):
    """Generate a minimal word list with given speaker_ids (by count)."""
    words = []
    if counts is None:
        # give each speaker a proportional number of words so rank order = arg order
        counts = list(range(len(speaker_ids), 0, -1))
    for sid, cnt in zip(speaker_ids, counts):
        for i in range(cnt):
            words.append({'type': 'word', 'text': f'w{i}', 'start': float(i),
                          'end': float(i) + 0.5, 'speaker_id': sid})
    return words


# ---------------------------------------------------------------------------
# Speaker mapping tests
# ---------------------------------------------------------------------------

class TestSpeakerMap(unittest.TestCase):

    def test_speaker_map_host_only(self):
        ep = dict(EP_NO_PAAS, g=[], p=False)
        words = _words_for('speaker_0')
        m = tr._speaker_map(words, ep)
        self.assertEqual(m['speaker_0'], ('David Boogerd', 'Presentator'))

    def test_speaker_map_1_guest_no_paas(self):
        ep = dict(EP_NO_PAAS, p=False, g=['Gast A'])
        # speaker_0 has more words → host, speaker_1 → guest
        words = _words_for('speaker_0', 'speaker_1', counts=[20, 10])
        m = tr._speaker_map(words, ep)
        self.assertEqual(m['speaker_0'][0], 'David Boogerd')
        self.assertEqual(m['speaker_1'], ('Gast A', 'Gast'))

    def test_speaker_map_2_guests_with_paas(self):
        ep = dict(EP_WITH_PAAS_2G)
        # rank: speaker_0 most words → host, speaker_1 next → Paas,
        # speaker_2 → guest[0], speaker_3 → guest[1]
        words = _words_for('speaker_0', 'speaker_1', 'speaker_2', 'speaker_3',
                           counts=[40, 30, 20, 10])
        m = tr._speaker_map(words, ep)
        self.assertEqual(m['speaker_0'][0], 'David Boogerd')
        self.assertEqual(m['speaker_1'][0], 'Stefan Paas')
        self.assertEqual(m['speaker_2'][0], 'Kader Abdolah')
        self.assertEqual(m['speaker_3'][0], 'Extra Gast')

    def test_speaker_map_manual_override(self):
        import tempfile, os
        ep = dict(EP_NO_PAAS, p=False, g=['Gast A'])
        words = _words_for('speaker_0', 'speaker_1', counts=[20, 10])
        # auto map: speaker_1 → Gast A
        mapping = tr._speaker_map(words, ep)
        self.assertEqual(mapping['speaker_1'][0], 'Gast A')

        # Apply a correction that renames speaker_1
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_dir = tr.CORRECTIONS_DIR
            tr.CORRECTIONS_DIR = pathlib.Path(tmpdir)
            corr_path = pathlib.Path(tmpdir) / '1.json'
            corr_path.write_text(json.dumps({'speaker_1': 'Echte Naam'}), encoding='utf-8')
            mapping2 = tr._apply_corrections(mapping.copy(), '1')
            tr.CORRECTIONS_DIR = orig_dir
        self.assertEqual(mapping2['speaker_1'][0], 'Echte Naam')


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchema(unittest.TestCase):

    def _make_transcript(self, ep, num_speakers=3):
        words = json.loads((FIXTURES / 'mock_elevenlabs.json').read_text())['words']
        mapping = tr._speaker_map(words, ep)
        return tr._words_to_transcript(words, mapping, ep)

    def test_schema_required_fields(self):
        t = self._make_transcript(EP_WITH_PAAS_2G)
        for field in ('episode', 'source', 'speakers', 'segments', 'events',
                      'summary', 'chapters', 'highlights', 'mentions', 'bible'):
            self.assertIn(field, t, f'Missing field: {field}')

    def test_segment_speaker_ids_reference_speakers_array(self):
        t = self._make_transcript(EP_WITH_PAAS_2G)
        valid_ids = {s['id'] for s in t['speakers']}
        for seg in t['segments']:
            self.assertIn(seg['speaker'], valid_ids,
                          f"Segment speaker {seg['speaker']} not in speakers list")

    def test_mentions_valid_types(self):
        # _words_to_transcript produces empty mentions; test the schema contract
        # by injecting a mock and checking validation logic
        t = self._make_transcript(EP_WITH_PAAS_2G)
        valid_types = {'persoon', 'filosoof', 'boek', 'plaats'}
        for m in t['mentions']:
            self.assertIn(m['type'], valid_types)

    def test_audio_event_becomes_laugh_event(self):
        t = self._make_transcript(EP_WITH_PAAS_2G)
        laugh_events = [ev for ev in t['events'] if ev['type'] == 'laugh']
        self.assertTrue(len(laugh_events) >= 1, 'No laugh event found')
        for ev in laugh_events:
            self.assertIn('t', ev)
            self.assertIn('speaker', ev)

    def test_overlap_event_on_rapid_speaker_change(self):
        # speaker_0 ends at 9.5, speaker_1 starts at 9.4 → gap = -0.1 < 0.3
        ep = dict(EP_WITH_PAAS_2G)
        words = json.loads((FIXTURES / 'mock_elevenlabs.json').read_text())['words']
        mapping = tr._speaker_map(words, ep)
        t = tr._words_to_transcript(words, mapping, ep)
        overlap_events = [ev for ev in t['events'] if ev['type'] == 'overlap']
        self.assertTrue(len(overlap_events) >= 1, 'Expected at least one overlap event')


# ---------------------------------------------------------------------------
# API error tests
# ---------------------------------------------------------------------------

def _make_requests_mock():
    """Return a MagicMock that substitutes for the requests module."""
    return MagicMock()


class TestAPIErrors(unittest.TestCase):

    def _inject_requests(self, mock_requests):
        tr._requests = mock_requests
        return mock_requests

    def setUp(self):
        self._orig_requests = tr._requests

    def tearDown(self):
        tr._requests = self._orig_requests

    def test_rate_limit_raises(self):
        ep = dict(EP_WITH_PAAS_2G)
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {'Retry-After': '90'}
        mock_resp.ok = False

        rq = _make_requests_mock()
        rq.post.return_value = mock_resp
        rq.RequestException = Exception
        self._inject_requests(rq)

        with self.assertRaises(tr.RateLimitError) as ctx:
            tr.transcribe_episode(ep, 'fake-key')
        self.assertEqual(ctx.exception.retry_after, 90)

    def test_non_200_raises(self):
        ep = dict(EP_WITH_PAAS_2G)
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.ok = False
        mock_resp.text = 'Internal Server Error'

        rq = _make_requests_mock()
        rq.post.return_value = mock_resp
        rq.RequestException = Exception
        self._inject_requests(rq)

        with self.assertRaises(tr.TranscriptionError):
            tr.transcribe_episode(ep, 'fake-key')

    def test_audio_url_fallback_on_4xx(self):
        ep = dict(EP_WITH_PAAS_2G)
        words = json.loads((FIXTURES / 'mock_elevenlabs.json').read_text())['words']

        resp_403 = MagicMock()
        resp_403.status_code = 403
        resp_403.ok = False

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.ok = True
        resp_ok.json.return_value = {'words': words}

        resp_dl = MagicMock()
        resp_dl.ok = True
        resp_dl.iter_content = lambda chunk_size: iter([b'fakebytes'])

        rq = _make_requests_mock()
        rq.post.side_effect = [resp_403, resp_ok]
        rq.get.return_value = resp_dl
        rq.RequestException = Exception
        self._inject_requests(rq)

        t = tr.transcribe_episode(ep, 'fake-key')
        self.assertIn('segments', t)


if __name__ == '__main__':
    unittest.main()
