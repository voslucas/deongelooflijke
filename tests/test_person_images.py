"""Portrait prefetch, incremental retry and local-only rendering regressions."""
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

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import person_images as portraits
site = importlib.import_module('5b_build_site')
URL = 'https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Portrait.jpg/250px-Portrait.jpg'


def image_bytes(size=(180, 400)):
    output = io.BytesIO()
    Image.new('RGBA', size, (255, 0, 0, 128)).save(output, 'PNG')
    return output.getvalue()


def write(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


def test_selected_sources_deduplicate_and_new_analysis_is_prefetched(tmp_path):
    write(tmp_path, 'data/analysis/1.json', {'people': [{'wiki_image': URL.replace('250px', '240px')}]})
    write(tmp_path, 'data/persons_mentioned/person.json', {'wiki_image': URL})
    write(tmp_path, 'data/wiki_cache.json', {'candidate': [{'thumbnail_url': 'https://unused.example/image.jpg'}]})
    assert portraits.collect_images(tmp_path) == [URL]
    with patch.object(portraits, 'download_image', return_value=image_bytes()) as download:
        urls = portraits.prepare_person_images(tmp_path, tmp_path / 'output')
        assert download.call_count == 1
        path = tmp_path / 'output' / urls[URL].lstrip('/')
        with Image.open(path) as image:
            assert image.format == 'JPEG'
            assert image.size == (144, 320)
        assert not (path.parent / 'index.json').exists()
        assert portraits.prepare_person_images(tmp_path, tmp_path / 'second') == urls
        assert download.call_count == 1
        new = URL.replace('Portrait', 'New')
        write(tmp_path, 'data/analysis/2.json', {'people': [{'wiki_image': new}]})
        assert new in portraits.prepare_person_images(tmp_path, tmp_path / 'output')
        assert download.call_count == 2


def test_cooldown_offline_retry_and_corrupt_cache(tmp_path):
    write(tmp_path, 'data/analysis/1.json', {'people': [{'wiki_image': URL}]})
    with patch.object(portraits, 'download_image', side_effect=OSError('unavailable')) as download:
        assert portraits.prepare_person_images(tmp_path, tmp_path / 'output') == {}
        portraits.prepare_person_images(tmp_path, tmp_path / 'output')
        download.assert_called_once()
    with patch.object(portraits, 'download_image', return_value=image_bytes()) as download:
        assert portraits.prepare_person_images(tmp_path, tmp_path / 'output', offline=True) == {}
        portraits.prepare_person_images(tmp_path, tmp_path / 'output')
        download.assert_not_called()
        urls = portraits.prepare_person_images(tmp_path, tmp_path / 'output', retry_missing=True)
        download.assert_called_once()
        filename = pathlib.Path(urls[URL]).name
        (tmp_path / 'data/person_images' / filename).write_bytes(b'broken')
        portraits.prepare_person_images(tmp_path, tmp_path / 'output')
        assert download.call_count == 2


@pytest.mark.parametrize('payload', [b'<html>error</html>', image_bytes((1, 1))])
def test_reject_invalid_images(payload):
    with pytest.raises(Exception):
        portraits.normalize_image(payload)


def test_download_validates_response_type_and_limits_bytes():
    class Response:
        headers = {'Content-Type': 'text/html'}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, count): return b'x' * count
    response = Response()
    with patch.object(portraits.urllib.request, 'urlopen', return_value=response):
        with pytest.raises(ValueError, match='not an image'):
            portraits.download_image(URL)
        response.headers = {'Content-Type': 'image/jpeg'}
        with pytest.raises(ValueError, match='download limit'):
            portraits.download_image(URL)


def test_all_static_person_rendering_uses_local_images(tmp_path, monkeypatch):
    local = '/data/person_images/portrait.jpg'
    monkeypatch.setattr(site, '_PERSON_IMAGE_URLS', {URL: local})
    person = {'n': 'Example Person', 'name': 'Example Person', 'slug': 'example-person',
              'img': URL, 'eps': [], 'x': 1, 'c': 'persoon'}
    data = site.SiteData()
    other = dict(person, slug='other-person', n='Other Person')
    data.people_list = [person, other]
    data.people_dict = {'example-person': person}
    data.persons_detail = {'example-person': {'name': 'Example Person', 'wiki_image': URL}}
    data.ep_by_num = {}
    data.years = []
    pages = [site.people_panel_html([{'name': 'Example Person', 'wiki_image': URL}])]
    with patch.object(site, 'write_page', side_effect=lambda path, title, html, **kw: pages.append(html)):
        site.build_persons_list(data, tmp_path)
        site.build_person_detail(data, 'example-person', tmp_path)
    for html in pages:
        assert local in html
        assert 'thumb.wikimedia.org' not in html
    assert pages[2].count(local) == 2  # Hero and related-person recommendation.
    assert site.wiki_thumb(True) == ''
    monkeypatch.setattr(site, '_PERSON_IMAGE_URLS', {})
    assert '<img' not in site.people_panel_html([{'name': 'Example Person', 'wiki_image': URL}])


@pytest.mark.skipif(shutil.which('node') is None, reason='Node required')
def test_legacy_resolver_uses_local_map_only():
    template = (ROOT / 'site/src/index.template.html').read_text(encoding='utf-8')
    resolver = 'function wikiThumb(' + template.split('function wikiThumb(', 1)[1].split('function peoplePanel(', 1)[0]
    script = 'const D={person_images:' + json.dumps({URL: '/data/person_images/portrait.jpg'}) + '};\n' + resolver
    script += '\n' + 'if(wikiThumb(' + json.dumps(URL.replace('250px', '240px')) + ')!=="data/person_images/portrait.jpg")throw Error("missing local portrait");'
    script += '\nif(wikiThumb("https://example.com/missing.jpg")||wikiThumb(true))throw Error("remote fallback");'
    result = subprocess.run(['node', '-'], input=script, encoding='utf-8', capture_output=True)
    assert result.returncode == 0, result.stderr
