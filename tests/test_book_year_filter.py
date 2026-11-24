"""Book rankings use episode years and remain searchable after switching years."""
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


def test_book_year_rankings(tmp_path):
    books = [dict(n=f'Book {i}', book_key=f'book-{i}', author='René',
                  x=20-i, yr={'2025': 20-i},
                  eps=[{'d': '2025-01-01'}] * (20-i)) for i in range(11)]
    books.append(dict(n='New favourite', book_key='new', author='Author',
                      x=3, yr={'2026': 3}, eps=[{'d': '2026-01-01'}] * 3))
    books[0]['yr']['2026'] = 1
    books[0]['eps'].append({'d': '2026-01-02'})
    site.build_books_list(SimpleNamespace(books_list=books), tmp_path)
    html = (tmp_path / 'boeken/index.html').read_text(encoding='utf-8')
    assert 'id="bkyears"' in html
    assert 'aria-pressed="true">Alle jaren' in html
    rankings = dict(re.findall(r'<template data-book-year="(.*?)">(.*?)</template>', html))
    assert set(rankings) == {'', '2025', '2026'}
    assert rankings[''].count('class="pm-card"') == 10
    assert 'data-title="book 10 rene"' in rankings['2025']
    year = rankings['2026']
    assert year.index('href="/boek/new/"') < year.index('href="/boek/book-0/"')
    assert '3 afleveringen' in year
    assert '1 aflevering<' in year
    assert 'href="/boek/book-1/"' not in year


@pytest.mark.skipif(not shutil.which('node'), reason='JavaScript runtime required')
def test_book_year_switch_preserves_search():
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
const match = el({title: 'a book rene'}), other = el({title: 'another author'});
list.items = [other];
list.querySelectorAll = () => list.items;
list.replaceChildren = node => { list.items = node.items; };
top.replaceChildren = node => { top.node = node; };
chips.querySelectorAll = () => [all, year];
const makeTemplate = (year, items) => ({dataset: {bookYear: year}, content: {
  children: [el({ranking: year}), Object.assign(el(), {items})]}});
const templates = [makeTemplate('', [other]), makeTemplate('2026', [match, other])];
const ids = {'bk-q': query, bklist: list, bktop: top, bkyears: chips};
const document = {getElementById: id => ids[id], querySelectorAll: () => templates};
const source = fs.readFileSync('site/src/app.js', 'utf8');
vm.runInNewContext(source.slice(source.indexOf('  function initBooksFilter()'),
  source.indexOf('  // ── Episode detail: tabs')) + '\ninitBooksFilter();', {document});
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
