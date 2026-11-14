"""Tests for scripts/transcribe_azure.py — speaker mapping, schema validation."""
import json, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

import transcribe_azure as tr

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


def _phrases_for(*speaker_ids, counts=None):
    """Generate Azure-format phrases with given integer speaker_ids."""
    if counts is None:
        counts = list(range(len(speaker_ids), 0, -1))
    phrases = []
    t_ms = 0
    for sid, cnt in zip(speaker_ids, counts):
        phrases.append({
            'speaker': sid,
            'words': [{'word': f'w{i}'} for i in range(cnt)],
            'text': ' '.join(f'w{i}' for i in range(cnt)),
            'offsetMilliseconds': t_ms,
            'durationMilliseconds': cnt * 500,
        })
        t_ms += cnt * 500
    return phrases


# ---------------------------------------------------------------------------
# Speaker mapping tests
# ---------------------------------------------------------------------------

class TestSpeakerMap(unittest.TestCase):

    def test_speaker_map_host_only(self):
        ep = dict(EP_NO_PAAS, g=[], p=False)
        phrases = _phrases_for(0)
        m = tr._speaker_map(phrases, ep)
        self.assertEqual(m[0], ('David Boogerd', 'Presentator'))

    def test_speaker_map_1_guest_no_paas(self):
        ep = dict(EP_NO_PAAS, p=False, g=['Gast A'])
        # speaker 0 has more words → host, speaker 1 → guest
        phrases = _phrases_for(0, 1, counts=[20, 10])
        m = tr._speaker_map(phrases, ep)
        self.assertEqual(m[0][0], 'David Boogerd')
        self.assertEqual(m[1], ('Gast A', 'Gast'))

    def test_speaker_map_2_guests_with_paas(self):
        ep = dict(EP_WITH_PAAS_2G)
        # rank: 0 most words → host, 1 → Paas, 2 → guest[0], 3 → guest[1]
        phrases = _phrases_for(0, 1, 2, 3, counts=[40, 30, 20, 10])
        m = tr._speaker_map(phrases, ep)
        self.assertEqual(m[0][0], 'David Boogerd')
        self.assertEqual(m[1][0], 'Stefan Paas')
        self.assertEqual(m[2][0], 'Kader Abdolah')
        self.assertEqual(m[3][0], 'Extra Gast')

    def test_speaker_map_caps_at_expected(self):
        # Extra spurious Azure speaker 4 should not appear in the mapping
        ep = dict(EP_NO_PAAS, p=False, g=['Gast A'])
        phrases = _phrases_for(0, 1, 4, counts=[20, 10, 5])
        m = tr._speaker_map(phrases, ep)
        self.assertNotIn(4, m)
        self.assertEqual(len(m), 2)

    def test_speaker_map_manual_override(self):
        import tempfile
        ep = dict(EP_NO_PAAS, p=False, g=['Gast A'])
        phrases = _phrases_for(0, 1, counts=[20, 10])
        mapping = tr._speaker_map(phrases, ep)

        # Build a minimal transcript and apply a correction that renames S2
        response_json = {'phrases': phrases}
        t = tr._azure_to_transcript(response_json, mapping, ep)
        # S2 should be 'Gast A' initially
        s2 = next(s for s in t['speakers'] if s['id'] == 'S2')
        self.assertEqual(s2['name'], 'Gast A')

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_dir = tr.CORRECTIONS_DIR
            tr.CORRECTIONS_DIR = pathlib.Path(tmpdir)
            corr_path = pathlib.Path(tmpdir) / '1.json'
            corr_path.write_text(json.dumps({'S2': 'Echte Naam'}), encoding='utf-8')
            t2 = tr._apply_corrections(dict(t), '1')
            tr.CORRECTIONS_DIR = orig_dir

        s2_after = next(s for s in t2['speakers'] if s['id'] == 'S2')
        self.assertEqual(s2_after['name'], 'Echte Naam')


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchema(unittest.TestCase):

    def _make_transcript(self, ep):
        phrases = _phrases_for(0, 1, 2, 3, counts=[40, 30, 20, 10])
        mapping = tr._speaker_map(phrases, ep)
        return tr._azure_to_transcript({'phrases': phrases}, mapping, ep)

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

    def test_overlap_event_on_rapid_speaker_change(self):
        # Two speakers with an overlapping transition (gap < 300 ms)
        ep = dict(EP_WITH_PAAS_2G)
        phrases = [
            {'speaker': 0, 'text': 'hello', 'words': [{'word': 'hello'}],
             'offsetMilliseconds': 0, 'durationMilliseconds': 9500},
            {'speaker': 1, 'text': 'world', 'words': [{'word': 'world'}],
             'offsetMilliseconds': 9400, 'durationMilliseconds': 1000},
        ]
        mapping = tr._speaker_map(phrases, ep)
        t = tr._azure_to_transcript({'phrases': phrases}, mapping, ep)
        overlap_events = [ev for ev in t['events'] if ev['type'] == 'overlap']
        self.assertTrue(len(overlap_events) >= 1, 'Expected at least one overlap event')


if __name__ == '__main__':
    unittest.main()
