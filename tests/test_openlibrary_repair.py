"""Verify conservative work matching and language/edition boundaries."""
import pathlib
import sys
import importlib
import json
import io
import pytest
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
from book_covers import normalize_image
import repair_books_openlibrary as repair


def test_author_and_title_guards():
    assert repair.title_score('The Anxious Generation', 'The Anxious Generation: A Subtitle') >= .90
    assert repair.title_score('The Anxious Generation', 'The Righteous Mind') < .90
    assert repair.author_matches('Jonathan Haidt', ['Jonathan Haidt'])
    assert not repair.author_matches('Jonathan Haidt', ['Jonathan Edwards'])
    assert not repair.author_matches('', ['Jonathan Haidt'])
    assert repair.author_matches('Dick Frans Swaab', ['D.F. Swaab'])
    assert not repair.author_matches('Dick Frans Swaab', ['Daniel Swaab'])
    assert repair.author_matches('Albert Camus, Jan Pieter van der Sterre', ['Albert Camus'])


class Library:
    def api(self, path, **params):
        if path.startswith('/isbn/'):
            return None
        if path == '/search.json':
            return {'docs': [{'key': '/works/1', 'title': 'The Republic', 'author_name': ['Modern Author']}]}
        if path == '/works/1.json':
            return {'key': '/works/1'}
        if path == '/works/1/editions.json':
            return {'entries': [
                {'key': '/books/english', 'title': 'The Republic', 'languages': [{'key': '/languages/eng'}], 'isbn_13': ['9780000000001']},
                {'key': '/books/dutch', 'title': 'De staat', 'languages': [{'key': '/languages/dut'}], 'isbn_13': ['9780000000002']},
            ]}
        raise AssertionError(path)


def test_english_recommendation_keeps_english_edition():
    edition, _, _ = repair.resolve(Library(), {'title': 'The Republic', 'author': 'Modern Author'})
    assert edition['key'] == '/books/english'
    assert repair.language_preference('Ethica', {'published_year': '1677'}) == 'dut'
    assert repair.language_preference('De staat', {'language': 'en'}) == 'dut'


def test_duplicate_work_clusters_with_same_title_are_not_ambiguous():
    class DuplicatedLibrary(Library):
        def api(self, path, **params):
            if path == '/search.json':
                return {'docs': [
                    {'key': '/works/1', 'title': 'THE REPUBLIC', 'author_name': ['Modern Author']},
                    {'key': '/works/2', 'title': 'The Republic', 'author_name': ['Modern Author']}]}
            return super().api(path, **params)
    edition, work, _ = repair.resolve(DuplicatedLibrary(), {'title': 'The Republic', 'author': 'Modern Author'})
    assert work['key'] == '/works/1'
    assert edition['key'] == '/books/english'


def test_known_isbn_never_borrows_other_edition_fields():
    edition, work, match = repair.resolve(Library(), {
        'title': 'The Republic', 'author': 'Modern Author', 'isbn13': '9780000000003'})
    assert edition is None
    assert work['key'] == '/works/1'
    assert match == 'work-only'


def test_ancient_author_prefers_modern_dutch_even_with_english_title():
    assert repair.language_preference('Confessions', {'author': 'Saint Augustine', 'language': 'en'}) == 'dut'
    assert repair.author_matches('Aurelius Augustinus', ['Augustine of Hippo'])
    assert repair.dutch_lookup_title('Confessiones', 'Augustinus') == 'Belijdenissen'


def test_isbn_checks_and_pairing():
    assert repair.valid_isbn13('9798587278479')
    assert not repair.valid_isbn13('9798587278478')
    assert repair.isbn10_from_isbn13('9798587278479') == ''
    assert repair.isbn10_from_isbn13('9780060850524') == '0060850523'
    assert repair.catalogue_isbn13('0060850523') == '9780060850524'


def test_new_isbn_preserves_original_slug_route(tmp_path, monkeypatch):
    site = importlib.import_module('5b_build_site')
    monkeypatch.setattr(site, 'ROOT', tmp_path)
    directory = tmp_path / 'dist/books'
    directory.mkdir(parents=True)
    record = {'key': 'de-staat', 'isbn13': '9780000000002', 'title': 'De staat'}
    (directory / 'de-staat.json').write_text(json.dumps(record), encoding='utf-8')
    data = site.load_data(tmp_path / 'dist')
    assert data.books_detail['de-staat'] == record
    assert data.books_detail['9780000000002'] == record


def test_classical_recommendation_checks_dutch_before_foreign_isbn():
    class ClassicalLibrary(Library):
        def api(self, path, **params):
            if path.startswith('/isbn/'):
                return {'key': '/books/english', 'works': [{'key': '/works/1'}],
                        'languages': [{'key': '/languages/eng'}]}
            return super().api(path, **params)
    edition, _, match = repair.resolve(ClassicalLibrary(), {
        'title': 'De Officiis', 'recommended_title': 'De officiis',
        'author': 'Cicero', 'isbn13': '9780000000001', 'description': 'Existing summary'})
    assert edition['key'] == '/books/dutch'
    assert match == 'dutch-edition-preferred'


def test_translated_edition_title_matches_original_work_title():
    class TranslatedLibrary:
        def api(self, path, **params):
            edition = {'key': '/books/dutch', 'title': 'De pest', 'isbn_13': ['9780000000002'],
                       'covers': [123], 'languages': [{'key': '/languages/dut'}]}
            if path == '/search.json':
                assert 'title:' in params['q'] and 'author:' in params['q']
                return {'docs': [{'key': '/works/1', 'title': 'La Peste', 'author_name': ['Albert Camus'],
                                  'editions': {'docs': [{'key': '/books/dutch', 'title': 'De pest'}]}}]}
            if path == '/works/1.json':
                return {'key': '/works/1'}
            if path == '/books/dutch.json':
                return edition
            if path == '/works/1/editions.json':
                return {'entries': [edition]}
            raise AssertionError(path)
    edition, work, match = repair.resolve(TranslatedLibrary(), {'title': 'De pest', 'author': 'Albert Camus'})
    assert edition['key'] == '/books/dutch'
    assert work['key'] == '/works/1'
    assert match == 'title-author-dut'


@pytest.mark.parametrize('size', [(128, 170), (256, 340)])
def test_google_placeholder_is_rejected_after_resizing_and_reencoding(size):
    fixture = pathlib.Path(__file__).parent / 'fixtures/google-books-no-cover.jpg'
    with Image.open(fixture) as image:
        output = io.BytesIO()
        image.resize(size).save(output, 'PNG')
    with pytest.raises(ValueError, match='image-not-available'):
        normalize_image(output.getvalue())
