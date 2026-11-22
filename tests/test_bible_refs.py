"""Accented citations must include the same popup data as plain spellings."""
import importlib.util
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('static_site', ROOT / 'scripts/5b_build_site.py')
site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(site)


def test_accented_reference_includes_popup_verses(tmp_path):
    bible = tmp_path / 'data' / 'bible'
    analysis = tmp_path / 'data' / 'analysis'
    bible.mkdir(parents=True)
    analysis.mkdir()
    verses = {'7': 'Vraag en er zal je gegeven worden.', '8': 'Want ieder die vraagt ontvangt.'}
    (bible / 'MAT.json').write_text(json.dumps({'7': verses}), encoding='utf-8')
    (analysis / '327.json').write_text(
        json.dumps({'bible_refs': [{'ref': 'Mattheüs 7:7'}]}), encoding='utf-8')

    assert site.parse_ref('Mattheüs 7:7') == site.parse_ref('Mattheus 7:7') == ('MAT', 7, 7)
    data = site._build_bvdata(tmp_path)
    assert data['MAT.7.7'] == list(verses.values())
    old = site._BVDATA
    try:
        site._BVDATA = data
        html = site.bible_refs_html([{'ref': 'Mattheüs 7:7'}])
        assert 'data-bvref="MAT.7.7"' in html
        assert 'data-vv=' in html
        assert verses['7'] in html
    finally:
        site._BVDATA = old
