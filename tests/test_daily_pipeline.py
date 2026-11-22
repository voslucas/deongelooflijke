"""Regression tests for complete transcript input and resumable daily work."""
import importlib
import json
import pathlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import analyze_episode as analysis
import fetch_feed
import process_new_episodes as pipeline
import enrich_guest_bios as bios

books = importlib.import_module('9_enrich_books_detail')
wiki = importlib.import_module('8_enrich_people_wiki')


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


def test_analysis_sends_full_transcript_and_records_coverage(monkeypatch):
    transcript = {
        'speakers': [{'id': 'S1', 'name': 'David Boogerd'}, {'id': 'S2', 'name': 'Gast'}],
        'segments': [
            {'start': 0, 'speaker': 'S1', 'text': 'begin ' * 12000},
            {'start': 7200, 'speaker': 'S2', 'text': 'Unieke informatie aan het einde.'},
        ],
    }
    monkeypatch.setattr(analysis, '_load_feed', lambda key: {'n': 328, 'desc': 'Beschrijving'})
    monkeypatch.setattr(analysis, '_load_transcript', lambda key: transcript)
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(
        stop_reason='end_turn', content=[SimpleNamespace(type='text', text='{"themes": []}')],
        usage=SimpleNamespace(input_tokens=20000, output_tokens=100),
    )
    result = analysis.analyse_episode('328', client, analysis.DEFAULT_MODEL, 'system',
                                      enrich_books=False, recommend_similar=False)
    prompt = client.messages.create.call_args.kwargs['messages'][0]['content']
    assert len(prompt) > 60000
    assert '[120:00] Gast: Unieke informatie aan het einde.' in prompt
    assert '[00:00] David Boogerd: begin' in prompt
    assert 'ingekort' not in prompt
    assert result['transcript_input'] == {
        'characters': len(analysis._transcript_text(transcript)),
        'segments': 2, 'truncated': False,
    }


def test_analysis_rejects_truncated_output(monkeypatch):
    monkeypatch.setattr(analysis, '_load_feed', lambda key: {'n': 328})
    monkeypatch.setattr(analysis, '_load_transcript', lambda key: {'segments': []})
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(stop_reason='max_tokens')
    with pytest.raises(ValueError, match='incomplete extraction'):
        analysis.analyse_episode('328', client, analysis.DEFAULT_MODEL, 'system')


def test_pending_includes_unfinished_and_unnumbered_but_preserves_legacy(tmp_path):
    episodes = [
        {'n': 327, 'd': '2026-11-01'}, {'n': 328, 'd': '2026-11-08'},
        {'n': 329, 'd': '2026-11-15'}, {'n': 330, 'd': '2026-11-18'},
        {'n': 331, 'd': '2026-11-22'}, {'n': None, 'id': 'new', 'd': '2026-11-23'},
    ]
    write_json(tmp_path / 'data/episodes.json', {'eps': episodes})
    write_json(tmp_path / 'data/pipeline-settings.json', {'held_episodes': ['331']})
    for key in ['327', '328', '329']:
        for kind in ['transcripts', 'analysis']:
            write_json(tmp_path / f'data/{kind}/{key}.json', {})
    write_json(tmp_path / 'data/processing/328.json', {'complete': True})
    write_json(tmp_path / 'data/processing/329.json', {'complete': False})
    assert pipeline.pending_episodes(tmp_path) == ['329', '330', 'xnew']


def test_failed_stage_resumes_without_repeating_completed_work(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, 'ROOT', tmp_path)
    monkeypatch.setattr(pipeline, 'STATUS_DIR', tmp_path / 'data/processing')
    write_json(tmp_path / 'data/transcripts/328.json', {})
    write_json(tmp_path / 'data/analysis/328.json', {})
    write_json(tmp_path / 'data/word_index.json', {'328': {'filosofie': 10}})
    calls = []

    def run(script, *args):
        calls.append(script)
        if script == '9_enrich_books_detail.py':
            raise RuntimeError('temporary API failure')

    monkeypatch.setattr(pipeline, 'run', run)
    with pytest.raises(RuntimeError, match='temporary API failure'):
        pipeline.process_episode('328')
    status = json.loads((tmp_path / 'data/processing/328.json').read_text())
    assert not status['complete']
    assert status['steps']['wikipedia']
    assert 'book_details' not in status['steps']
    calls.clear()
    monkeypatch.setattr(pipeline, 'run', lambda script, *args: calls.append(script))
    pipeline.process_episode('328')
    assert calls == ['9_enrich_books_detail.py', 'enrich_guest_bios.py',
                     '9_build_word_index.py', '10_collect_persons.py']
    assert json.loads((tmp_path / 'data/processing/328.json').read_text())['complete']


@pytest.mark.parametrize('payload', [b'<html>Not a feed</html>', b'<rss><channel/></rss>'])
def test_feed_failure_preserves_previous_snapshot(tmp_path, monkeypatch, payload):
    destination = tmp_path / 'feed.xml'
    destination.write_text('previous good feed')
    response = Mock(content=payload)
    monkeypatch.setattr(fetch_feed.requests, 'get', lambda *args, **kwargs: response)
    with pytest.raises(ValueError):
        fetch_feed.fetch_feed(destination)
    assert destination.read_text() == 'previous good feed'


def test_book_details_are_scoped_to_selected_episode(tmp_path, monkeypatch):
    monkeypatch.setattr(books, 'DIR_ANALYSIS', tmp_path)
    write_json(tmp_path / '327.json', {'books': [{'isbn13': 'old-isbn'}]})
    write_json(tmp_path / '328.json', {'books': [{'volume_id': 'new-volume', 'title': 'Nieuw'}]})
    assert set(books._collect_unique_books('328')) == {'vol-new-volume'}


def test_biographies_use_analysis_guests_instead_of_feed_heuristics(tmp_path, monkeypatch):
    monkeypatch.setattr(bios, 'EPISODES_JSON', tmp_path / 'episodes.json')
    monkeypatch.setattr(bios, 'DIR_ANALYSIS', tmp_path / 'analysis')
    write_json(tmp_path / 'episodes.json', {'eps': [
        {'n': 328, 'g': ['Wrong feed guess']}, {'n': 329, 'g': ['Existing guest']},
    ]})
    write_json(tmp_path / 'analysis/328.json', {'guests': ['Tinneke Beeckman']})
    episodes = bios._episodes_with_guests()
    assert episodes[0]['g'] == ['Tinneke Beeckman']
    assert episodes[1]['g'] == ['Existing guest']


def test_wikipedia_network_failure_is_retried_not_marked_as_no_match(monkeypatch):
    monkeypatch.setattr(wiki, 'wiki_search', lambda *args: None)
    cache = {}
    with pytest.raises(RuntimeError, match='retry later'):
        wiki.wiki_search_cached('New person', 'nl', cache)
    assert cache == {}


def test_related_episode_retry_handles_truncated_response():
    client = Mock()
    matches = [{'n': n, 'reason': 'Gedeeld onderwerp'} for n in (1, 2, 3)]
    client.messages.create.side_effect = [
        SimpleNamespace(stop_reason='max_tokens', content=[
            SimpleNamespace(type='text', text='[{"n": 1, "reason": "unfinished')]),
        SimpleNamespace(stop_reason='end_turn', content=[
            SimpleNamespace(type='text', text=json.dumps(matches))]),
    ]
    catalogue = [{'n': n, 't': 'Test'} for n in (1, 2, 3, 327)]
    assert analysis._recommend_similar(client, 'test-model', {'n': 327}, {}, catalogue) == matches
    assert [call.kwargs['max_tokens'] for call in client.messages.create.call_args_list] == [4000, 8000]


def test_related_episode_failure_is_not_silently_returned_as_empty_list():
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(
        stop_reason='end_turn', content=[SimpleNamespace(type='text', text='[{"reason": "broken')])
    with pytest.raises(ValueError, match='failed after two attempts'):
        analysis._recommend_similar(client, 'test-model', {'n': 327}, {}, [])


def test_main_extraction_is_preserved_when_related_episode_lookup_fails(monkeypatch):
    monkeypatch.setattr(analysis, '_load_feed', lambda key: {'n': 327})
    monkeypatch.setattr(analysis, '_load_transcript', lambda key: {'segments': []})
    monkeypatch.setattr(analysis, '_recommend_similar', Mock(side_effect=RuntimeError('API unavailable')))
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(
        stop_reason='end_turn', content=[SimpleNamespace(type='text', text='{"summary_tldr": "Saved summary"}')],
        usage=SimpleNamespace(input_tokens=200, output_tokens=100),
    )
    result = analysis.analyse_episode('327', client, 'test-model', 'system',
                                     all_eps=[{'n': 1}], enrich_books=False)
    assert result['summary_tldr'] == 'Saved summary'
    assert result['similar_status'] == 'failed'
    assert result['similar_error'] == 'API unavailable'


def test_similar_only_preserves_existing_extraction_and_enrichment(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, 'ROOT', tmp_path)
    monkeypatch.setattr(analysis, 'DIR_OUT', tmp_path / 'analysis')
    monkeypatch.setattr(analysis, 'DIR_FEED', tmp_path / 'feed')
    monkeypatch.setattr(analysis, 'EPISODES_JSON', tmp_path / 'episodes.json')
    monkeypatch.setattr(sys, 'argv', ['analyze_episode.py', '--episode', '327', '--similar-only'])
    monkeypatch.setitem(sys.modules, 'anthropic', Mock())
    monkeypatch.setattr(analysis, '_load_transcript', Mock(side_effect=AssertionError('Must not load transcript')))
    monkeypatch.setattr(analysis, '_verify_books', Mock(side_effect=AssertionError('Must not rematch books')))
    related = [{'n': 1, 'reason': 'Gedeeld onderwerp'}]
    monkeypatch.setattr(analysis, '_recommend_similar', Mock(return_value=related))
    original = {'episode': 327, 'summary_tldr': 'Preserve this', 'model': 'original-model',
                'usage': {'input_tokens': 50689}, 'books': [{'isbn13': '123'}],
                'people': [{'name': 'Jezus', 'wiki_checked': True}],
                'similar': [], 'similar_status': 'failed', 'similar_error': 'old error'}
    write_json(tmp_path / 'analysis/327.json', original)
    write_json(tmp_path / 'feed/327.json', {'n': 327})
    write_json(tmp_path / 'episodes.json', {'eps': [{'n': 1, 't': 'Other episode'}]})
    analysis.main()
    repaired = json.loads((tmp_path / 'analysis/327.json').read_text())
    expected = {**original, 'similar': related, 'similar_status': 'complete',
                'similar_model': analysis.DEFAULT_MODEL}
    expected.pop('similar_error')
    assert repaired == expected
