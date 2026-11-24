"""Person year filters update rankings, counts and the searchable remainder."""
import importlib
import pathlib
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
site = importlib.import_module('5b_build_site')


def test_person_year_rankings(tmp_path):
    persons = [dict(n=f'Person {i}', c='persoon', x=20-i, mx=99,
                    eps=[{'d': '2025-01-01', 'x': 2}] * (20-i)) for i in range(11)]
    persons.append(dict(n='New favourite', c='filosoof', x=3, mx=6,
                        eps=[{'d': '2026-01-01', 'x': 2}] * 3))
    persons[0]['eps'].append({'d': '2026-01-02', 'x': 4})
    # Year counts can contain merged transcript and analysis counts: use episode dates.
    persons[0]['yr'] = {'2026': 999, '2030': 1}
    persons.append(dict(n='Excluded book', c='boek', x=999,
                        eps=[{'d': '2031-01-01'}]))
    site.build_persons_list(SimpleNamespace(people_list=persons), tmp_path)
    html = (tmp_path / 'personen/index.html').read_text(encoding='utf-8')
    assert 'id="pmyears"' in html
    assert 'aria-pressed="true">Alle jaren' in html
    rankings = dict(re.findall(r'<template data-person-year="(.*?)">(.*?)</template>', html))
    assert set(rankings) == {'', '2025', '2026'}
    assert rankings[''].count('class="pm-card"') == 10
    assert 'data-name="person 10"' in rankings['2025']
    year = rankings['2026']
    assert year.index('href="/persoon/new-favourite/"') < year.index('href="/persoon/person-0/"')
    assert '3 afleveringen' in year
    assert '1 aflevering<' in year
    assert '6× totaal' in year
    assert '4× totaal' in year
    assert '99×' not in year
    assert 'href="/persoon/person-1/"' not in year
    assert 'Excluded book' not in html
    assert persons[0]['mx'] == 99
    assert len(persons[0]['eps']) == 21


def test_empty_persons_list(tmp_path):
    site.build_persons_list(SimpleNamespace(people_list=[]), tmp_path)
    html = (tmp_path / 'personen/index.html').read_text(encoding='utf-8')
    assert 'id="pmyears"' not in html
    assert '<template data-person-year=""><div class="pm-cards"></div><div></div></template>' in html


@pytest.mark.skipif(not shutil.which('node'), reason='JavaScript runtime required')
def test_person_year_switch_preserves_search():
    script = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
function element(dataset = {}) {
  return {dataset, events: {}, attrs: {}, classes: new Set(),
    addEventListener(name, fn) { this.events[name] = fn; },
    setAttribute(name, value) { this.attrs[name] = value; },
    classList: {toggle(name, on) { this.owner.classes[on ? 'add' : 'delete'](name); }},
    cloneNode() { return this; }};
}
function el(data) { const e = element(data); e.classList.owner = e; return e; }
const all = el({yr: ''}), year = el({yr: '2026'});
const query = el(); query.value = 'RENÉ';
const list = el(), top = el(), chips = el();
const match = el({name: 'rene descartes'}), other = el({name: 'another person'});
list.items = [other];
list.querySelectorAll = () => list.items;
list.replaceChildren = node => { list.items = node.items; };
top.replaceChildren = node => { top.node = node; };
chips.querySelectorAll = () => [all, year];
const makeTemplate = (year, items) => ({dataset: {personYear: year}, content: {
  children: [el({ranking: year}), Object.assign(el(), {items})]}});
const templates = [makeTemplate('', [other]), makeTemplate('2026', [match, other])];
const ids = {'pm-q': query, pmlist: list, pmtop: top, pmyears: chips};
const document = {getElementById: id => ids[id], querySelectorAll: () => templates};
const source = fs.readFileSync('site/src/app.js', 'utf8');
vm.runInNewContext(source.slice(source.indexOf('  function initPersonsFilter()'),
  source.indexOf('  // ── Books list: filter')) + '\ninitPersonsFilter();', {document});
year.events.click();
assert.equal(top.node.dataset.ranking, '2026');
assert.equal(year.attrs['aria-pressed'], 'true');
assert.equal(all.attrs['aria-pressed'], 'false');
assert.equal(match.classes.has('hidden'), false);
assert.equal(other.classes.has('hidden'), true);
query.value = ''; query.events.input();
assert.equal(other.classes.has('hidden'), false);
all.events.click();
assert.equal(top.node.dataset.ranking, '');
assert.equal(all.attrs['aria-pressed'], 'true');
"""
    result = subprocess.run([shutil.which('node'), '-e', script], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
