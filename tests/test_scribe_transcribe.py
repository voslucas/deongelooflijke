"""Scribe request contract, conversion and preservation checks; no paid API calls."""
import json
import pathlib
import sys
from types import SimpleNamespace

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import transcribe as scribe
import transcribe_azure as mai


EP = {'n': 1, 't': 'Test', 'mp3': 'https://example.com/audio.mp3',
      'g': ['Guest'], 'p': True}


def word(text, start, speaker='speaker_0', **extra):
    return {'type': 'word', 'text': text, 'start': start, 'end': start + .4,
            'speaker_id': speaker, **extra}


def test_request_sends_cast_count_and_production_settings():
    def handle(request):
        assert request.url == 'https://api.elevenlabs.io/v1/speech-to-text'
        assert request.headers['xi-api-key'] == 'test-key'
        assert request.headers['content-type'].startswith('multipart/form-data')
        body = request.read().decode()
        for name, value in {'num_speakers': '3', 'model_id': 'scribe_v3',
                            'language_code': 'nl', 'diarize': 'true',
                            'tag_audio_events': 'false', 'no_verbatim': 'false',
                            'timestamps_granularity': 'word', 'source_url': EP['mp3']}.items():
            assert f'name="{name}"\r\n\r\n{value}\r\n' in body
        return httpx.Response(200, json={'words': [word('Hallo.', 0)]})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        transcript = scribe.transcribe_episode(EP, 'test-key', client=client)
    assert transcript['source']['model'] == 'elevenlabs/scribe_v3'


def test_conversion_schema_text_events_and_word_count_ranking():
    words = [word('Hallo', 0), {'type': 'spacing', 'text': ' '},
             word(',', .5), word('wereld.', 1),
             {'type': 'audio_event', 'text': '(music)', 'start': 1.5, 'end': 2},
             word('Ja.', 1.8, 'speaker_1'), word('Hoi.', 3, 'speaker_2')]
    transcript = scribe._words_to_transcript({'words': words}, EP)
    expected = mai._azure_to_transcript({'phrases': []}, {}, EP)
    assert transcript.keys() == expected.keys()
    assert transcript['events'] == []
    assert transcript['segments'][0] == {'start': 0, 'end': 1.4, 'speaker': 'S1', 'text': 'Hallo, wereld.'}
    assert [s['name'] for s in transcript['speakers']] == ['David Boogerd', 'Stefan Paas', 'Guest']
    assert {s['speaker'] for s in transcript['segments']} <= {s['id'] for s in transcript['speakers']}


def test_fixture_conversion_preserves_all_speech_words():
    data = json.loads((ROOT / 'tests/fixtures/mock_elevenlabs.json').read_text())
    transcript = scribe._words_to_transcript(data, EP)
    assert sum(len(s['text'].split()) for s in transcript['segments']) == sum(w['type'] == 'word' for w in data['words'])


@pytest.mark.parametrize('ep,count', [({'g': [], 'p': False}, 1),
                                    ({'g': [], 'p': True}, 2), (EP, 3),
                                    ({'g': ['A', 'B'], 'p': True}, 4)])
def test_expected_cast(ep, count):
    assert scribe._expected_speakers(ep) == count


def test_unassigned_and_excess_speakers_keep_speech_without_host_attribution():
    ep = dict(EP, g=[], p=False)
    transcript = scribe._words_to_transcript({'words': [word('Hallo wereld', 0),
                  word('Extra', 1, 'extra'), word('Onbekend', 2, None)]}, ep)
    assert len(transcript['speakers']) == 3
    assert transcript['segments'][1]['speaker'] != 'S1'
    assert transcript['segments'][2]['speaker'] != 'S1'


@pytest.mark.parametrize('data', [{'words': []}, {'words': [word('Bad', -1)]},
                                  {'words': [word('Bad', 0, end=None)]},
                                  {'words': [word('Bad', float('nan'))]}])
def test_invalid_or_empty_response_is_not_saved(data):
    with pytest.raises(mai.TranscriptionError):
        scribe._words_to_transcript(data, EP)


def test_existing_output_is_never_overwritten_or_sent_to_api(tmp_path, monkeypatch):
    path = tmp_path / 'existing.json'
    path.write_text('original transcript')
    with pytest.raises(FileExistsError):
        scribe._save_new(path, {})
    monkeypatch.setattr(scribe, '_load_api_key', lambda _: 'fake-key')
    monkeypatch.setattr(scribe, 'transcribe_episode', lambda *a, **kw: pytest.fail('Paid API must be skipped'))
    assert scribe.main(['--episode', '1', '--output', str(path)]) == 0
    assert path.read_text() == 'original transcript'


@pytest.mark.parametrize('status,body,error', [(401, {'detail': 'invalid key'}, mai.TranscriptionError),
                                              (429, {}, mai.RateLimitError),
                                              (200, {'text': 'missing timestamps'}, mai.TranscriptionError)])
def test_api_failures(status, body, error):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))) as client:
        with pytest.raises(error):
            scribe._request(client, 'test-key', scribe.ENDPOINT, 2, source_url=EP['mp3'])


def test_identification_targets_custom_output(tmp_path, monkeypatch):
    profiles = tmp_path / 'data' / 'voice-profiles'
    profiles.mkdir(parents=True)
    (profiles / 'test.npy').touch()
    calls = []
    monkeypatch.setattr(scribe, 'ROOT', tmp_path)
    monkeypatch.setitem(sys.modules, 'identify_speakers', SimpleNamespace(
        identify_episode=lambda *args, **kwargs: calls.append((args, kwargs))))
    output = tmp_path / 'comparison.json'
    scribe._identify('x5005', output)
    assert calls == [(('x5005',), {'threshold': .75, 'apply': True, 'transcript_path': output})]
