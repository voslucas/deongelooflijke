"""A clean stages 4 + 5b build must publish tracked runtime data without stage 5."""
import importlib
import json
import pathlib
import re
import shutil
import sys
import pytest
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
split = importlib.import_module('4_split_data')
site = importlib.import_module('5b_build_site')


@pytest.mark.parametrize('extension,size', [
    ('jpg', (1200, 800)), ('jpeg', (800, 1200)), ('jfif', (600, 600)),
    ('png', (300, 200)), ('webp', (30, 40)),
])
def test_profile_images_are_resized_and_encoded_as_jpeg(tmp_path, extension, size):
    source = tmp_path / 'data/persons/images' / f'guest.{extension}'
    source.parent.mkdir(parents=True)
    image = Image.new('RGB', size, 'red')
    image.save(source)
    original = source.read_bytes()
    out = tmp_path / 'output'

    site.copy_data_files(tmp_path / 'dist', out, tmp_path)

    with Image.open(out / 'data/persons/images/guest.jpg') as portrait:
        assert portrait.format == 'JPEG'
        assert portrait.size == (min(72, *size),) * 2
        assert portrait.getpixel((portrait.width // 2, portrait.height // 2))[0] > 240
    assert source.read_bytes() == original
    assert len(list((out / 'data/persons/images').iterdir())) == 1


def test_profile_images_crop_the_center_and_handle_transparency(tmp_path):
    directory = tmp_path / 'data/persons/images'
    directory.mkdir(parents=True)
    image = Image.new('RGBA', (600, 200), 'blue')
    image.paste((0, 0, 0, 0), (200, 0, 400, 200))
    image.save(directory / 'guest.png')
    out = tmp_path / 'output'

    site.copy_data_files(tmp_path / 'dist', out, tmp_path)

    with Image.open(out / 'data/persons/images/guest.jpg') as portrait:
        assert portrait.size == (72, 72)
        assert all(channel > 245 for channel in portrait.getpixel((36, 36)))
        assert all(channel > 245 for channel in portrait.getpixel((5, 36)))


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
    (tmp_path / 'site/src/over.md').write_text(
        (ROOT / 'site/src/over.md').read_text(encoding='utf-8'), encoding='utf-8')
    shutil.copytree(ROOT / 'design-system/assets/fonts',
                    tmp_path / 'design-system/assets/fonts')
    shutil.copytree(ROOT / 'design-system/assets/icons',
                    tmp_path / 'design-system/assets/icons')
    monkeypatch.setattr(site, 'ROOT', tmp_path)
    out = tmp_path / 'site/static'
    monkeypatch.setattr(sys, 'argv', ['5b_build_site.py', '--offline', '--output-dir', str(out)])
    site.main()

    home = (out / 'index.html').read_text(encoding='utf-8')
    assert 'href="/assets/fonts/fonts.css"' in home
    assert 'href="/favicon.ico"' in home
    assert 'href="/site.webmanifest"' in home
    assert 'href="/apple-touch-icon.png"' in home
    assert (out / 'favicon.ico').is_file()
    manifest = json.loads((out / 'site.webmanifest').read_text(encoding='utf-8'))
    for icon in manifest['icons']:
        with Image.open(out / icon['src']) as image:
            assert f'{image.width}x{image.height}' == icon['sizes']
    assert 'fonts.googleapis.com' not in home
    css = (out / 'assets/fonts/fonts.css').read_text(encoding='utf-8')
    assert 'https://' not in css
    font_urls = re.findall(r'url\(([^)]+)\)', css)
    assert font_urls
    for font_url in font_urls:
        assert (out / 'assets/fonts' / font_url).read_bytes()[:4] == b'wOF2'
    for family in ('lora', 'spectral'):
        assert 'SIL OPEN FONT LICENSE' in (out / 'assets/fonts' / f'{family}-OFL.txt').read_text(encoding='utf-8')

    assert json.loads((out / 'data/transcripts/327.json').read_text(encoding='utf-8')) == transcript
    assert json.loads((out / 'data/word_index.json').read_text(encoding='utf-8')) == words
    person = (out / 'persoon/karl-marx/index.html').read_text(encoding='utf-8')
    assert 'Distinctive source detail' in person
    assert 'Stale detail' not in person
    assert 'https://nl.wikipedia.org/wiki/Karl_Marx' in person
    about = (out / 'over/index.html').read_text(encoding='utf-8')
    assert '<h1>Over</h1>' in about
    assert '<h2>Nerdhoekje</h2>' in about
    assert '<code>nl_core_news_sm</code>' in about
    assert 'href="mailto:deongelooflijkearchief@outlook.com"' in about
    assert '<a href="/over/" class="on">Over</a>' in about
    assert '<a href="/over/" class="">Over</a>' in person
    assert '<loc>https://www.deongelooflijkearchief.nl/over/</loc>' in (out / 'sitemap.xml').read_text(encoding='utf-8')
