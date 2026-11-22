"""A clean stages 4 + 5b build must publish tracked runtime data without stage 5."""
import importlib
import json
import pathlib
import sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
split = importlib.import_module('4_split_data')
site = importlib.import_module('5b_build_site')


@pytest.mark.parametrize('stale_staging', [False, True])
def test_clean_ci_build_publishes_transcripts_word_index_and_person_details(tmp_path, monkeypatch, stale_staging):
    def write(relative, data):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8')

    episode = json.loads((ROOT / 'tests/fixtures/sample_episode.json').read_text(encoding='utf-8'))
    write('data/episodes.json', {'eps': [episode], 'bios': {}, 'built': '2026-11-22'})
    transcript = {'episode': 327, 'speakers': [{'id': 'S1', 'name': 'David Boogerd'}],
                  'segments': [{'speaker': 'S1', 'start': 0, 'end': 3, 'text': 'Test transcript.'}]}
    write('data/transcripts/327.json', transcript)
    words = {'327': {'geloof': 3}}
    write('data/word_index.json', words)
    write('data/analysis/327.json', {'people': [{'name': 'Karl Marx'}]})
    write('data/persons_mentioned/karl-marx.json', {
        'name': 'Karl Marx', 'notes': ['Distinctive source detail'],
        'wiki_url': 'https://nl.wikipedia.org/wiki/Karl_Marx'})

    dist = tmp_path / 'site/dist/data'
    for attr, value in {
        'ROOT': tmp_path, 'EPISODES_JSON': tmp_path / 'data/episodes.json',
        'TRANSCRIPTS_DIR': tmp_path / 'data/transcripts',
        'ANALYSIS_DIR': tmp_path / 'data/analysis',
        'BOOKS_DIR': tmp_path / 'data/books', 'OUT_DIR': dist,
    }.items():
        monkeypatch.setattr(split, attr, value)
    split.main()
    # Reproduce a clean CI checkout: none of the legacy builder's staging exists.
    assert not (dist / 'transcripts').exists()
    assert not (dist / 'word_index.json').exists()
    assert not (dist / 'persons_mentioned').exists()

    # Also check that stale local intermediates cannot override tracked sources.
    if stale_staging:
        write('site/dist/data/transcripts/327.json', {'stale': True})
        write('site/dist/data/word_index.json', {'stale': True})
        write('site/dist/data/persons_mentioned/karl-marx.json', {'notes': ['Stale detail']})
    (tmp_path / 'site/src').mkdir(parents=True)
    (tmp_path / 'site/src/index.template.html').write_text('<style>body{margin:0}</style>', encoding='utf-8')
    monkeypatch.setattr(site, 'ROOT', tmp_path)
    out = tmp_path / 'site/static'
    monkeypatch.setattr(sys, 'argv', ['5b_build_site.py', '--offline', '--output-dir', str(out)])
    site.main()

    assert json.loads((out / 'data/transcripts/327.json').read_text(encoding='utf-8')) == transcript
    assert json.loads((out / 'data/word_index.json').read_text(encoding='utf-8')) == words
    person = (out / 'persoon/karl-marx/index.html').read_text(encoding='utf-8')
    assert 'Distinctive source detail' in person
    assert 'Stale detail' not in person
    assert 'https://nl.wikipedia.org/wiki/Karl_Marx' in person
