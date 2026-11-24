"""Cover identity, download fallback, incremental caching and static-page privacy."""
import importlib
import io
import json
import pathlib
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import book_covers as covers

site = importlib.import_module('5b_build_site')


def image_bytes(size=(120, 180)):
    output = io.BytesIO()
    Image.new('RGB', size, 'red').save(output, 'PNG')
    return output.getvalue()


@pytest.fixture
def library(tmp_path):
    for directory in ('books', 'analysis'):
        (tmp_path / 'data' / directory).mkdir(parents=True)
    book = {'isbn13': '9780141976365', 'volume_id': 'volume_one',
            'thumbnail': 'https://books.google.com/books/content?id=volume_one&imgtk=expired',
            'title': 'Selected book'}
    (tmp_path / 'data/books/book.json').write_text(json.dumps(book), encoding='utf-8')
    (tmp_path / 'data/analysis/1.json').write_text(json.dumps({'books': [book]}), encoding='utf-8')
    return tmp_path, book


def test_open_library_then_google_and_cached_across_aliases(library):
    root, book = library
    calls = []

    def download(url):
        calls.append(url)
        if 'openlibrary.org' in url:
            return image_bytes((1, 1))  # A successful HTTP response can still be a placeholder.
        return image_bytes()

    with patch.object(covers, 'download_image', side_effect=download):
        urls = covers.prepare_covers(root, root / 'output')
    assert 'openlibrary.org' in calls[0]
    assert 'books.google.com' in calls[1]
    assert 'imgtk=' not in calls[1]
    assert urls['isbn:' + book['isbn13']] == urls['vol:volume_one']
    assert (root / 'output' / urls['vol:volume_one'].lstrip('/')).is_file()
    with patch.object(covers, 'download_image', side_effect=AssertionError('cache must avoid network')):
        assert covers.prepare_covers(root, root / 'second') == urls


def test_new_episode_without_detail_record_downloads_missing_cover(library):
    root, _ = library
    with patch.object(covers, 'download_image', return_value=image_bytes()):
        original = covers.prepare_covers(root, root / 'output')
    (root / 'data/analysis/2.json').write_text(json.dumps({'books': [
        {'volume_id': 'new_edition', 'title': 'New episode book'}]}), encoding='utf-8')
    with patch.object(covers, 'download_image', return_value=image_bytes()) as download:
        updated = covers.prepare_covers(root, root / 'output')
    assert download.call_count == 1
    assert 'vol:new_edition' in updated
    assert updated['vol:volume_one'] == original['vol:volume_one']


def test_failed_download_cooldown_retry_and_offline(library):
    root, _ = library
    with patch.object(covers, 'download_image', side_effect=OSError('unavailable')) as download:
        assert covers.prepare_covers(root, root / 'output') == {}
        attempts = download.call_count
        assert covers.prepare_covers(root, root / 'output') == {}
        assert download.call_count == attempts
    with patch.object(covers, 'download_image', return_value=image_bytes()) as download:
        assert covers.prepare_covers(root, root / 'output', offline=True) == {}
        download.assert_not_called()
        assert covers.prepare_covers(root, root / 'output', retry_missing=True)
        assert download.called


def test_corrupt_cache_is_replaced(library):
    root, _ = library
    with patch.object(covers, 'download_image', return_value=image_bytes()):
        urls = covers.prepare_covers(root, root / 'output')
    filename = pathlib.Path(urls['vol:volume_one']).name
    (root / 'data/book_covers' / filename).write_bytes(b'broken')
    with patch.object(covers, 'download_image', return_value=image_bytes()) as download:
        assert covers.prepare_covers(root, root / 'output')
        assert download.called


def test_reject_nonimages_and_tiny_placeholders():
    for payload in (b'<html>rate limited</html>', image_bytes((1, 1))):
        with pytest.raises(Exception):
            covers.normalize_image(payload)


def test_matching_uses_selected_edition_identifiers_not_title(library):
    root, book = library
    other_edition = dict(book, isbn13='9789028282384', volume_id='another_edition',
                         thumbnail='https://books.google.com/books/content?id=another_edition')
    (root / 'data/analysis/2.json').write_text(json.dumps({'books': [other_edition]}), encoding='utf-8')
    groups = covers.collect_books(root)
    assert len(groups) == 2
    assert not (groups[0]['aliases'] & groups[1]['aliases'])


def test_every_static_cover_location_uses_local_images(library):
    root, book = library
    with patch.object(covers, 'download_image', return_value=image_bytes()):
        urls = covers.prepare_covers(root, root / 'output')
    data = site.SiteData()
    data.books_list = [{'n': book['title'], 'author': 'Author', 'x': 1,
                        'book_key': book['isbn13'] if i == 0 else f'vol-other_{i}',
                        'bk_thumb': book['thumbnail'],
                        'eps': [], 'yr': {}} for i in range(12)]
    data.books_detail = {book['isbn13']: book}
    data.ep_by_num = {}
    data.years = []
    pages = []
    with patch.object(site, '_COVER_URLS', urls), patch.object(
            site, 'write_page', side_effect=lambda path, title, html, **kw: pages.append(html)):
        # Episode sidebar, overview cards AND rows, detail hero AND recommendations.
        pages.append(site.book_panel_html([book]))
        site.build_books_list(data, root / 'output')
        site.build_book_detail(data, data.books_list[0], root / 'output')
        pages.append(site.bk_img_html('', '', 40))
    assert len(pages) == 4
    for html in pages:
        assert 'books.google.' not in html
        assert 'covers.openlibrary.org' not in html
        assert 'data-fb=' not in html
    assert pages[0].count('/data/book_covers/') == 1
    # Year rankings repeat these covers in inert templates. Count the visible
    # overview; the provider-URL checks above cover the templates as well.
    assert pages[1].split('<template', 1)[0].count('/data/book_covers/') == 12
    assert pages[2].count('/data/book_covers/') == 11  # Hero plus ten recommendations.
    assert '<img' not in pages[3]


@pytest.mark.skipif(shutil.which('node') is None, reason='Node required to exercise the legacy renderer')
def test_legacy_renderer_resolves_isbn_volume_and_thumbnail():
    template = (ROOT / 'site/src/index.template.html').read_text(encoding='utf-8')
    renderer = template.split('function bkImg(', 1)[1].split('const SAFE_TAGS', 1)[0]
    script = """
const D={covers:{'isbn:9780141976365':'/data/book_covers/one.jpg',
                 'vol:selected_volume':'/data/book_covers/two.jpg'}};
const esc=s=>s;
""" + 'function bkImg(' + renderer + """
for(const [key,thumb,file] of [
  ['9780141976365','','one.jpg'],
  ['vol-selected_volume','','two.jpg'],
  ['','https://books.google.com/books/content?id=selected_volume','two.jpg']
]) {
  const html=bkImg(key,thumb,40,56,'2px');
  if(!html.includes('src="data/book_covers/'+file+'"') || html.includes('https://'))
    throw new Error('Remote or missing cover: '+html);
}
if(bkImg('','',40,56,'2px').includes('<img'))throw new Error('Missing cover must use icon');
"""
    result = subprocess.run(['node', '-'], input=script, encoding='utf-8', capture_output=True)
    assert result.returncode == 0, result.stderr
