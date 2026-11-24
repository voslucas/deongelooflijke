"""Unanalysed feed entries must not enter public pages or statistics."""
import importlib
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
split = importlib.import_module('4_split_data')
site = importlib.import_module('5b_build_site')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.mark.parametrize('pending_analysis', [None, '', '{}', '{broken',
    '{"episode":328,"model":"test"}', '{"themes":[],"summary_tldr":""}'])
def test_filter_precedes_keywords_and_statistics_and_episode_returns_after_analysis(
        tmp_path, monkeypatch, pending_analysis):
    for name, path in {
        'EPISODES_JSON': 'master.json', 'ANALYSIS_DIR': 'analysis',
        'TRANSCRIPTS_DIR': 'transcripts', 'OUT_DIR': 'output', 'BOOKS_DIR': 'books',
    }.items():
        monkeypatch.setattr(split, name, tmp_path / path)
    sample = json.loads((ROOT / 'tests/fixtures/sample_episode.json').read_text(encoding='utf-8'))
    episodes = [sample, dict(sample, n=328, t='Pending episode', g=['Pending guest'])]
    write(split.EPISODES_JSON, {'eps': episodes})
    write(split.ANALYSIS_DIR / '327.json', {'summary_tldr': 'Actual analysis'})
    if pending_analysis is not None:
        (split.ANALYSIS_DIR / '328.json').write_text(pending_analysis, encoding='utf-8')
    for number in (327, 328):
        write(split.TRANSCRIPTS_DIR / f'{number}.json', {
            'episode': number, 'speakers': [{'id': 'S1', 'name': f'Guest {number}'}],
            'segments': [{'speaker': 'S1', 'start': 0, 'end': 10, 'text': 'Some words'}],
        })
    write(split.OUT_DIR / 'episodes/328.json', episodes[1])
    scored = []
    original = split.compute_tfidf
    def score(eps):
        scored.append([e['n'] for e in eps])
        original(eps)
    monkeypatch.setattr(split, 'compute_tfidf', score)
    split.main()
    assert scored == [[327]]
    assert json.loads((split.OUT_DIR / 'index.json').read_text()) == ['327']
    assert not (split.OUT_DIR / 'episodes/328.json').exists()
    speakers = json.loads((split.OUT_DIR / 'speakers.json').read_text())
    assert [speaker['name'] for speaker in speakers] == ['Guest 327']
    assert len(json.loads(split.EPISODES_JSON.read_text())['eps']) == 2
    write(split.ANALYSIS_DIR / '328.json', {'summary_tldr': 'Now analysed'})
    split.main()
    assert json.loads((split.OUT_DIR / 'index.json').read_text()) == ['327', '328']
    assert (split.OUT_DIR / 'episodes/328.json').exists()


@pytest.mark.parametrize('keys', [[], ['327']])
def test_static_loader_obeys_even_an_empty_publication_index(tmp_path, monkeypatch, keys):
    monkeypatch.setattr(site, 'ROOT', tmp_path)
    write(tmp_path / 'dist/index.json', keys)
    sample = json.loads((ROOT / 'tests/fixtures/sample_episode.json').read_text(encoding='utf-8'))
    write(tmp_path / 'dist/episodes/327.json', sample)
    write(tmp_path / 'dist/episodes/328.json', dict(sample, n=328))
    data = site.load_data(tmp_path / 'dist')
    assert list(data.ep_by_key) == keys
    assert [str(ep['n']) for ep in data.all_eps] == keys
