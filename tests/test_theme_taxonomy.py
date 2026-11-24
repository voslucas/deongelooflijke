"""Model output and stale analysis must never create editorial categories."""
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
from theme_taxonomy import validate_themes


@pytest.mark.parametrize('values', [
    ['Bijbel & Jezus (Bijbel, Jezus, evangeliën, Christus, Bergrede, apostelen, Paulus)'],
    ['Invented category'], ['Geloof & God'], 'Politiek', [None], None,
    ['Politiek', 'Politiek'],
    ['Politiek', 'God & geloof', 'Bijbel & Jezus', 'Geschiedenis', 'Dood & rouw'],
])
def test_rejects_noncanonical_themes(values):
    with pytest.raises(ValueError):
        validate_themes(values)


def test_analysis_rejects_themes_before_enrichment_or_save(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, '_load_feed', lambda key: {'n': 58})
    monkeypatch.setattr(analysis, '_load_transcript', lambda key: {'segments': []})
    enrich = Mock()
    monkeypatch.setattr(analysis, '_verify_books', enrich)
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(
        stop_reason='end_turn', content=[SimpleNamespace(type='text', text=json.dumps({
            'themes': ['Invented category'], 'books': [{'title': 'Book'}],
        }))],
    )
    with pytest.raises(ValueError, match='unknown theme labels'):
        analysis.analyse_episode('58', client, 'test', 'system')
    enrich.assert_not_called()
    monkeypatch.setattr(analysis, 'DIR_OUT', tmp_path)
    path = tmp_path / '58.json'
    path.write_text('existing analysis', encoding='utf-8')
    with pytest.raises(ValueError, match='unknown theme labels'):
        analysis.save_analysis('58', {'themes': ['Invented category']})
    assert path.read_text(encoding='utf-8') == 'existing analysis'


@pytest.mark.parametrize('source', ['master', 'analysis'])
def test_split_rejects_unknown_themes_before_writing(tmp_path, monkeypatch, source):
    split = importlib.import_module('4_split_data')
    monkeypatch.setattr(split, 'EPISODES_JSON', tmp_path / 'episodes.json')
    monkeypatch.setattr(split, 'ANALYSIS_DIR', tmp_path / 'analysis')
    monkeypatch.setattr(split, 'OUT_DIR', tmp_path / 'output')
    split.ANALYSIS_DIR.mkdir()
    split.EPISODES_JSON.write_text(json.dumps({'eps': [{
        'n': 58, 't': 'Title', 'x': '',
        'th': ['Invented category'] if source == 'master' else ['Politiek'],
    }]}), encoding='utf-8')
    (split.ANALYSIS_DIR / '58.json').write_text(json.dumps({
        'themes': ['Invented category'] if source == 'analysis' else ['Politiek'],
    }), encoding='utf-8')
    with pytest.raises(ValueError, match='unknown theme labels'):
        split.main()
    assert not split.OUT_DIR.exists()


def test_archive_only_uses_editorial_themes():
    for path in (ROOT / 'data' / 'analysis').glob('*.json'):
        validate_themes(json.loads(path.read_text(encoding='utf-8'))['themes'], context=str(path))
    for ep in json.loads((ROOT / 'data' / 'episodes.json').read_text(encoding='utf-8'))['eps']:
        validate_themes(ep.get('th', []), context=str(ep.get('n')))
