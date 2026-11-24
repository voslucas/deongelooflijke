"""Catalogue layout variants and exact edition/language guards."""
import pathlib
import sys
import json
import io
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import repair_books_bibliotheek as catalogue_module
from repair_books_bibliotheek import Document, repair, search_results, versions


def test_single_print_edition_metadata_and_cover():
    document = Document('''<img src="https://leibniz.zbkb.nl/assets/id/PPN%3A123?sig=public&amp;width=320">
      <dl class="meta meta-version"><dt>Uitgever</dt><dd>Prometheus, Amsterdam</dd>
      <dt>ISBN</dt><dd>9789044662511</dd><dt>Kenmerken</dt><dd>385 pagina&#039;s</dd></dl>''')
    edition, = versions(document)
    assert edition['isbn'] == '9789044662511'
    assert edition['kenmerken'] == "385 pagina's"
    assert edition['ppn'] == '123'
    assert '&width=320' in edition['cover_url']


def test_multiple_editions_keep_metadata_together():
    document = Document('''<div data-version-identifier="1"><dl>
      <dt>ISBN</dt><dd>9789044651591</dd><dt>Kenmerken</dt><dd>276 pagina's</dd></dl></div>
      <div data-version-identifier="2"><dl><dt>ISBN</dt><dd>9789044651591</dd>
      <dt>Kenmerken</dt><dd>280 pagina's</dd></dl></div>''')
    first, second = versions(document)
    assert first['ppn'] == '1' and first['kenmerken'] == "276 pagina's"
    assert second['ppn'] == '2' and second['kenmerken'] == "280 pagina's"


def test_result_title_and_multiple_authors():
    document = Document('''<div class="content list-big">
      <a href="/catalogus/titel.123.html/book/"><span class="creator">David Boogerd | Stefan Paas</span>
      <span class="title">De ongelooflijke geschiedenis</span></a></div>''')
    result, = search_results(document)
    assert result['authors'] == ['David Boogerd', 'Stefan Paas']
    assert result['title'] == 'De ongelooflijke geschiedenis'


def test_foreign_edition_is_not_labeled_dutch():
    class Catalogue:
        def document(self, url):
            if 'catalogus.catalogus.html' in url:
                return Document('''<div class="content list-big"><a href="/catalogus/titel.1.html/book/">
                  <span class="creator">Plato</span><span class="title">Politeia</span></a></div>''')
            return Document('''<dl><dt>Taal</dt><dd>Engels</dd></dl><dl class="meta meta-version">
              <dt>ISBN</dt><dd>9780000000001</dd></dl>''')
    result = repair(Catalogue(), {'key': 'politeia', 'title': 'Politeia', 'author': 'Plato',
                                  'isbn13': '9780000000001'}, ['description'], {}, None, False)
    assert result['status'] == 'unresolved'


def test_local_reuse_repairs_a_typo_without_collapsing_a_series(tmp_path, monkeypatch):
    monkeypatch.setattr(catalogue_module, 'ROOT', tmp_path)
    books = tmp_path / 'data/books'
    covers = tmp_path / 'data/book_covers'
    books.mkdir(parents=True)
    covers.mkdir()
    Image.new('RGB', (120, 180), 'red').save(covers / 'cover.jpg')
    source = {'key': '9780000000001', 'isbn13': '9780000000001', 'title': 'Dorsvloer vol confetti',
              'author': 'Franca Treur', 'language': 'nl'}
    (books / 'source.json').write_text(json.dumps(source), encoding='utf-8')
    manifest = {'isbn:9780000000001': {'file': 'cover.jpg'}}
    record = {'key': 'dorstvloer-vol-confetti', 'title': 'Dorstvloer vol confetti', 'author': 'Franca Treur'}
    target = (record['key'], books / (record['key'] + '.json'), record, ['cover'])
    report = catalogue_module.reuse_existing_records([target], manifest, None, True)
    assert report[record['key']]['alias_of'] == source['key']
    repaired = json.loads(target[1].read_text(encoding='utf-8'))
    assert repaired['key'] == record['key']
    assert repaired['title'] == 'Dorsvloer vol confetti'
    source.update(title='Harry Potter and the Philosopher\'s Stone', author='J. K. Rowling')
    (books / 'source.json').write_text(json.dumps(source), encoding='utf-8')
    record.update(key='harry-potter', title='Harry Potter', author='J. K. Rowling')
    target = (record['key'], books / 'harry-potter.json', record, ['cover'])
    assert catalogue_module.reuse_existing_records([target], manifest, None, False) == {}


def test_title_first_tries_another_edition_after_image_404_and_rejects_graphic_adaptation():
    output = io.BytesIO()
    Image.new('RGB', (120, 180), 'red').save(output, 'PNG')
    class Catalogue:
        def document(self, url):
            if 'catalogus.catalogus.html' in url:
                return Document('''<div class="content list-big"><a href="/catalogus/titel.1.html/graphic/">
                  <span class="creator">Dick Matena | Jan Wolkers</span><span class="title">Turks fruit</span></a></div>
                  <div class="content list-big"><a href="/catalogus/titel.2.html/novel/">
                  <span class="creator">Jan Wolkers</span><span class="title">Turks fruit</span></a></div>''')
            assert 'graphic' not in url
            return Document('''<dl><dt>Taal</dt><dd>Nederlands</dd></dl>
              <div data-version-identifier="old"><img src="https://leibniz.zbkb.nl/old"><dl>
              <dt>ISBN</dt><dd>9789038898971</dd><dt>Verschenen</dt><dd>2014</dd></dl></div>
              <div data-version-identifier="new"><img src="https://leibniz.zbkb.nl/new"><dl>
              <dt>ISBN</dt><dd>9789029077033</dd><dt>Verschenen</dt><dd>2023</dd>
              <dt>Uitgever</dt><dd>Meulenhoff</dd><dt>Kenmerken</dt><dd>189 pagina's</dd></dl></div>''')
        def get(self, url):
            return None if url.endswith('/old') else output.getvalue()
    result = repair(Catalogue(), {'key': '9789038898971', 'title': 'Turks fruit', 'author': 'Jan Wolkers',
                                  'isbn13': '9789038898971', 'language': 'nl'}, ['cover'], {}, None, False,
                    title_first=True)
    assert result['status'] == 'repaired'
    assert result['isbn13'] == '9789029077033'
    assert result['cover'] == 'downloaded'
