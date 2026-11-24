"""One-time Bibliotheek.nl fallback for Dutch book metadata and local covers.

Run after repair_books_openlibrary.py. --apply writes records, covers and the
audit report. Public catalogue pages are fetched at most once per second and
cached in the system temporary directory. Original archive route keys survive.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import html
from html.parser import HTMLParser
import io
import json
import pathlib
import re
import tempfile
import threading
import time
import urllib.parse

import requests
from PIL import Image

from book_covers import aliases, normalize_image
from repair_books_openlibrary import (ROOT, author_matches, collect_targets,
                                     classical_author, dutch_lookup_title,
                                     catalogue_isbn13, isbn10_from_isbn13,
                                     valid_isbn13,
                                     language_preference, norm, placeholder,
                                     title_score, valid_cover, write_json)
from utils import slug

BASE = 'https://www.bibliotheek.nl'
REPORT = ROOT / 'data/book_repair_bibliotheek_report.json'
CACHE = pathlib.Path(tempfile.gettempdir()) / 'ongelooflijk-bibliotheek-repair'


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def nodes(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.nodes()

    def text(self):
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c for c in self.children).split())

    def has_class(self, value):
        return value in self.attrs.get('class', '').split()


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'img', 'meta', 'link', 'input', 'br', 'hr', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


class Catalogue:
    def __init__(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.local = threading.local()
        self.lock = threading.Lock()
        self.last = 0

    def get(self, url):
        path = CACHE / hashlib.sha256(url.encode()).hexdigest()
        if path.exists():
            return path.read_bytes()
        if not hasattr(self.local, 'session'):
            self.local.session = requests.Session()
            self.local.session.trust_env = False
        for attempt in range(3):
            with self.lock:
                time.sleep(max(0, 1.05 - (time.monotonic() - self.last)))
                self.last = time.monotonic()
            try:
                with self.local.session.get(url, timeout=(6, 15), stream=True,
                                            headers={'User-Agent': 'OngelooflijkArchief/1.0 (one-time catalogue repair)'}) as response:
                    response.raise_for_status()
                    payload = b''
                    for chunk in response.iter_content(65536):
                        payload += chunk
                        if len(payload) > 8 * 1024 * 1024:
                            raise ValueError('response exceeds size limit')
                    path.write_bytes(payload)
                    return payload
            except requests.RequestException as exc:
                if getattr(exc.response, 'status_code', None) == 404:
                    return None
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))

    def document(self, url):
        payload = self.get(url)
        return Document(payload.decode('utf-8')) if payload else None


def search_results(document):
    results = []
    for node in document.root.nodes():
        if not node.has_class('content') or not node.has_class('list-big'):
            continue
        children = list(node.nodes())
        links = [n.attrs['href'] for n in children if n.tag == 'a' and n.attrs.get('href', '').startswith('/catalogus/titel.')]
        titles = [n.text() for n in children if n.has_class('title')]
        authors = [part.strip() for n in children if n.has_class('creator') for part in n.text().split('|')]
        if links and titles:
            results.append({'url': BASE + links[0], 'title': titles[0], 'authors': authors})
    return results


def versions(document):
    result = []
    nodes = [n for n in document.root.nodes() if 'data-version-identifier' in n.attrs]
    single_cover = next((n.attrs['src'] for n in document.root.nodes()
                         if n.tag == 'img' and 'leibniz.zbkb.nl' in n.attrs.get('src', '')), '')
    if not nodes:
        nodes = [n for n in document.root.nodes() if n.tag == 'dl' and n.has_class('meta-version')]
    for node in nodes:
        ppn = node.attrs.get('data-version-identifier') or next(iter(re.findall(r'PPN%3A(\d+)', single_cover)), '')
        data = {'ppn': ppn}
        if node.tag == 'dl' and single_cover:
            data['cover_url'] = single_cover
        label = None
        for child in node.nodes():
            if child.tag == 'dt':
                label = norm(child.text())
            elif child.tag == 'dd' and label:
                data[label] = child.text()
                label = None
            elif child.tag == 'img' and 'leibniz.zbkb.nl' in child.attrs.get('src', ''):
                data['cover_url'] = child.attrs['src']
        result.append(data)
    return result


def repair(catalogue, record, missing, manifest, reference, apply, title_first=False):
    isbn = record.get('isbn13') or ''
    title = record.get('recommended_title') or record['title']
    if title_first:
        title = dutch_lookup_title(title, record.get('author'))
    primary = re.split(r':|\s[–—]\s|\.\s', title, maxsplit=1)[0]
    author = re.split(r',|;', record.get('author', ''))[0]
    author_part = classical_author(author) or (norm(author).split()[-1] if author else '')
    if author_part == 'augustine':
        author_part = 'augustinus'
    query = (primary + (' ' + author_part if author_part else '')) if title_first else (
        isbn or (primary + (' ' + author_part if author_part else '')))
    url = BASE + '/catalogus.catalogus.html?' + urllib.parse.urlencode({'q': query, 'type': 'Gedrukt_boek'})
    document = catalogue.document(url)
    results = search_results(document) if document else []
    def alternative_edition():
        alternate = dict(record, isbn13='', isbn10='')
        if isbn:
            alternate['original_isbn13'] = record.get('original_isbn13') or isbn
        return repair(catalogue, alternate, list(set(missing + ['cover'])), manifest, reference, apply, title_first=True)
    if record.get('title'):
        def candidate_title(result):
            return dutch_lookup_title(result['title'], record.get('author')) if title_first else result['title']
        results = [r for r in results if title_score(primary, candidate_title(r)) >= .90
                   and author_matches(record.get('author'), r['authors'])]
        results = [r for r in results if r['authors'] and author_matches(record.get('author'), r['authors'][:1])]
        if results:
            best = max(title_score(primary, candidate_title(r)) for r in results)
            results = [r for r in results if title_score(primary, candidate_title(r)) >= best - .01]
        if len({norm(candidate_title(r)) for r in results}) > 1:
            return {'status': 'unresolved', 'reason': 'ambiguous title/author results'}
    if not results and title_first and author_part:
        # Spoken titles can contain small spelling errors (e.g. Hoge/Hooge).
        # Search the author's catalogue and still require the title/name match.
        author_query = author_part if classical_author(author) else author
        author_url = BASE + '/catalogus.catalogus.html?' + urllib.parse.urlencode({'q': author_query, 'type': 'Gedrukt_boek'})
        author_document = catalogue.document(author_url)
        candidates = search_results(author_document) if author_document else []
        candidates = [r for r in candidates if title_score(primary, dutch_lookup_title(r['title'], record.get('author'))) >= .90
                      and r['authors'] and author_matches(record.get('author'), r['authors'][:1])]
        if candidates:
            best = max(title_score(primary, dutch_lookup_title(r['title'], record.get('author'))) for r in candidates)
            candidates = [r for r in candidates if title_score(primary, dutch_lookup_title(r['title'], record.get('author'))) >= best - .01]
            if len({norm(dutch_lookup_title(r['title'], record.get('author'))) for r in candidates}) == 1:
                results = candidates
    if not results:
        if title_first and isbn:
            # An exact ISBN is useful supporting evidence when a long or
            # unusual title is not indexed as expected.
            return repair(catalogue, record, missing, manifest, reference, apply, title_first=False)
        if isbn:
            return alternative_edition()
        return {'status': 'unresolved', 'reason': 'no matching print catalogue record'}
    for result in results[:3]:
        detail = catalogue.document(result['url'])
        if not detail:
            continue
        label, language = None, ''
        for node in detail.root.nodes():
            if node.tag == 'dt':
                label = norm(node.text())
            elif node.tag == 'dd' and label:
                if label == 'taal':
                    language = norm(node.text())
                label = None
        if 'nederlands' not in language:
            continue
        choices = versions(detail)
        if isbn and not title_first:
            choices = [v for v in choices if isbn in re.findall(r'\d{13}', v.get('isbn', ''))]
        else:
            choices = [v for v in choices if catalogue_isbn13(v.get('isbn', ''))]
        if not choices:
            continue
        def score(version):
            year = int(next(iter(re.findall(r'\b(?:1[4-9]|20)\d{2}\b', version.get('verschenen', ''))), '0'))
            exact = isbn and isbn in re.findall(r'\d{13}', version.get('isbn', ''))
            if classical_author(record.get('author')):
                return (year >= 1950, bool(version.get('cover_url')), year, bool(version.get('isbn')), exact)
            return (bool(version.get('cover_url')), exact, bool(version.get('isbn')), year)
        ranked = sorted(choices, key=score, reverse=True)
        chosen = ranked[0]
        if title_first and any(f in missing for f in ('cover', 'modern_dutch_edition', 'unverified_edition_cover')):
            # Catalogue image URLs can exist for editions whose asset is 404.
            # Try another edition before accepting that the work has no cover.
            for candidate in ranked[:6]:
                if not candidate.get('cover_url'):
                    continue
                try:
                    candidate_payload = catalogue.get(candidate['cover_url'])
                    if not candidate_payload:
                        continue
                    normalized = normalize_image(candidate_payload)
                    with Image.open(io.BytesIO(normalized)) as image:
                        if placeholder(image, reference):
                            continue
                    chosen = candidate
                    break
                except (OSError, ValueError, requests.RequestException):
                    continue
        updated = dict(record)
        selected_isbn = catalogue_isbn13(chosen.get('isbn', '')) or isbn
        reselected = selected_isbn != isbn
        fields = {'isbn13': selected_isbn, 'isbn10': isbn10_from_isbn13(selected_isbn), 'publisher': chosen.get('uitgever', ''),
                  'published_year': next(iter(re.findall(r'\b(?:1[4-9]|20)\d{2}\b', chosen.get('verschenen', ''))), ''),
                  'page_count': int(next(iter(re.findall(r'\b(\d+)\s+pagina', chosen.get('kenmerken', ''))), '0'))}
        for field, value in fields.items():
            if (value and not updated.get(field)) or not isbn or reselected:
                updated[field] = value
        if not isbn or reselected:
            updated['title'] = result['title']
            if isbn:
                updated['original_isbn13'] = record.get('original_isbn13') or isbn
            if updated.get('openlibrary_edition'):
                updated['original_openlibrary_edition'] = updated.pop('openlibrary_edition')
        if not updated.get('description'):
            descriptions = [n.attrs.get('content', '') for n in detail.root.nodes()
                            if n.tag == 'meta' and n.attrs.get('name') == 'description']
            if descriptions:
                updated['description'] = html.escape(descriptions[0])
        updated.update(language='nl', is_ebook=False, bibliotheek_url=result['url'], bibliotheek_ppn=chosen['ppn'])
        cover_status = 'existing'
        if any(f in missing for f in ('cover', 'modern_dutch_edition', 'unverified_edition_cover')) or reselected:
            cover_status = 'unavailable'
            cover_url = chosen.get('cover_url')
            if cover_url:
                try:
                    payload = catalogue.get(cover_url)
                    if payload:
                        payload = normalize_image(payload)
                        with Image.open(io.BytesIO(payload)) as image:
                            if placeholder(image, reference):
                                raise ValueError('placeholder image')
                        filename = hashlib.sha256(('bibliotheek:' + record['key']).encode()).hexdigest()[:24] + '.jpg'
                        if apply:
                            (ROOT / 'data/book_covers' / filename).write_bytes(payload)
                            for alias in (aliases(updated.get('isbn13'), updated.get('volume_id'), cover_url)
                                          + aliases(record.get('isbn13') or (record['key'] if re.fullmatch(r'\d{13}', record['key']) else ''),
                                                    thumbnail=record.get('thumbnail'))
                                          + aliases(thumbnail=record.get('thumbnail_large'))):
                                manifest[alias] = {'file': filename, 'source_url': cover_url}
                        updated['thumbnail'] = updated['thumbnail_large'] = cover_url
                        cover_status = 'downloaded'
                except (OSError, ValueError, requests.RequestException) as exc:
                    cover_status = 'error: ' + type(exc).__name__
        changes = [f for f in updated if updated[f] != record.get(f)]
        if apply and changes:
            write_json(ROOT / 'data/books' / (record['key'] + '.json'), updated)
        return {'status': 'repaired' if changes else 'unchanged', 'changed': changes, 'cover': cover_status,
                'url': result['url'], 'isbn13': selected_isbn,
                'still_missing': [f for f in ('description', 'isbn13', 'publisher', 'published_year', 'page_count') if not updated.get(f)]}
    if isbn and not title_first:
        return alternative_edition()
    return {'status': 'unresolved', 'reason': 'no matching Dutch print edition'}


def reuse_existing_records(targets, manifest, reference, apply):
    """Join otherwise unidentified mentions to an already verified local edition.

    Require a matching author and matching primary title (or a single small
    spelling difference with the same word count). This does not collapse a
    series title into one of its individual volumes.
    """
    existing = [json.loads(p.read_text(encoding='utf-8')) for p in (ROOT / 'data/books').glob('*.json')]
    report = {}
    def primary(title):
        title = norm(re.split(r':|\s[–—]\s', title, maxsplit=1)[0])
        title = re.sub(r'^(?:the|a|an|de|het|een)\s+', '', title)
        return re.sub(r'\b7\b', 'zeven', title)
    for key, path, record, missing in targets:
        classic = bool(classical_author(record.get('author')))
        if record.get('isbn13') and not ('cover' in missing or 'unverified_edition_cover' in missing
                                         or (classic and 'modern_dutch_edition' in missing)):
            continue
        raw_title = record.get('recommended_title') or record['title']
        title = primary(dutch_lookup_title(raw_title, record.get('author')) if classic else raw_title)
        desired = 'en' if language_preference(raw_title, record) == 'eng' else 'nl'
        if len(title) < 10:
            continue
        candidates = []
        for book in existing:
            primary_author = re.split(r',|;', book.get('author', ''))[0]
            if (book['key'] == key or not book.get('isbn13') or book.get('language') != desired
                    or not author_matches(record.get('author'), [primary_author])):
                continue
            if book.get('openlibrary_match') == 'work-only' and 'covers.openlibrary.org' in book.get('thumbnail', ''):
                continue
            other = primary(dutch_lookup_title(book['title'], book.get('author')) if classic else book['title'])
            exact = title.replace(' ', '') == other.replace(' ', '')
            from difflib import SequenceMatcher
            typo = len(title.split()) == len(other.split()) and SequenceMatcher(None, title, other).ratio() >= .96
            if not (exact or typo):
                continue
            identity = aliases(book.get('isbn13'), book.get('volume_id'), book.get('thumbnail'))
            cover = next((manifest[a] for a in identity if manifest.get(a, {}).get('file') and
                          valid_cover(ROOT / 'data/book_covers' / manifest[a]['file'], reference)), None)
            if cover:
                candidates.append((exact, book, cover))
        # Different primary titles from the same author need human review.
        if not candidates or len({primary(dutch_lookup_title(b['title'], b.get('author')) if classic else b['title'])
                                  for _, b, _ in candidates}) > 1:
            continue
        def rank(item):
            book = item[1]
            year = int(book['published_year']) if str(book.get('published_year', '')).isdigit() else 0
            return (item[0], not classic or year >= 1950, primary(book['title']) == title,
                    bool(book.get('description')), bool(book.get('page_count')), year)
        _, winner, cover = max(candidates, key=rank)
        updated = dict(winner, key=key, book_repair_alias_of=winner['key'])
        if record.get('volume_id'):
            updated['volume_id'] = record['volume_id']
        updated['recommended_title'] = record.get('recommended_title') or record['title']
        if record.get('isbn13') and record['isbn13'] != updated['isbn13']:
            updated['original_isbn13'] = record.get('original_isbn13') or record['isbn13']
        if apply:
            write_json(path, updated)
            for alias in (aliases(updated.get('isbn13'), updated.get('volume_id'), updated.get('thumbnail'))
                          + aliases(record.get('isbn13')) + aliases(key if re.fullmatch(r'\d{13}', key) else '')):
                manifest[alias] = cover
        report[key] = {'status': 'repaired', 'title': record['title'], 'alias_of': winner['key'], 'applied': apply}
    accumulated = {book['key']: {'status': 'repaired', 'title': book.get('recommended_title') or book['title'],
                                'alias_of': book['book_repair_alias_of'], 'applied': True}
                   for book in existing if book.get('book_repair_alias_of')}
    accumulated.update(report)
    write_json(ROOT / 'data/book_repair_alias_report.json', accumulated)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--key', action='append', help='Repair specified archive route keys only (repeatable)')
    parser.add_argument('--reuse-only', action='store_true', help='Join unidentified duplicates to verified local editions without HTTP')
    parser.add_argument('--title-first', action='store_true', help='Match title/author first and prefer a covered edition over the old ISBN')
    args = parser.parse_args()
    manifest_path = ROOT / 'data/book_covers/index.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    with Image.open(ROOT / 'data/book_covers/a0fb7fe96c499d4e7c090478.jpg') as image:
        reference = image.convert('RGB').resize((32, 40))
    report = json.loads(REPORT.read_text(encoding='utf-8')) if REPORT.exists() else {}
    if args.apply:
        # Recover completed downloads if a previous run stopped before its
        # manifest checkpoint. The deterministic filenames identify each job.
        for path in (ROOT / 'data/books').glob('*.json'):
            book = json.loads(path.read_text(encoding='utf-8'))
            filename = hashlib.sha256(('bibliotheek:' + book['key']).encode()).hexdigest()[:24] + '.jpg'
            if book.get('bibliotheek_url') and 'leibniz.zbkb.nl' in book.get('thumbnail', '') and valid_cover(ROOT / 'data/book_covers' / filename, reference):
                for alias in (aliases(book.get('isbn13'), book.get('volume_id'), book['thumbnail'])
                              + aliases(book['key'] if re.fullmatch(r'\d{13}', book['key']) else '')):
                    manifest[alias] = {'file': filename, 'source_url': book['thumbnail']}
                if not report.get(book['key'], {}).get('applied'):
                    report[book['key']] = {'status': 'repaired', 'title': book['title'], 'cover': 'downloaded',
                                           'url': book['bibliotheek_url'], 'applied': True, 'recovered_checkpoint': True}
        write_json(manifest_path, manifest)
        write_json(REPORT, report)
    all_targets = collect_targets(manifest, reference)
    targets = [t for t in all_targets
               if language_preference(t[2].get('recommended_title') or t[2]['title'], t[2]) == 'dut']
    if args.reuse_only:
        report = reuse_existing_records(all_targets, manifest, reference, args.apply)
        if args.apply:
            write_json(manifest_path, manifest)
        print(f'{len(report)} unidentified duplicate records matched locally', flush=True)
        targets = []
    if args.key:
        targets = [t for t in targets if t[0] in args.key]
    targets = [t for t in targets if args.key or args.title_first or not report.get(t[0], {}).get('applied')]
    catalogue = Catalogue()
    print(f'{len(targets)} Dutch records need catalogue fallback', flush=True)
    def process(target):
        key, _, record, missing = target
        record = dict(record, author=record.get('recommended_author') or record.get('author', ''))
        try:
            result = repair(catalogue, record, missing, manifest, reference, args.apply, title_first=args.title_first)
        except Exception as exc:
            result = {'status': 'error', 'reason': f'{type(exc).__name__}: {exc}'}
        result.update(title=record['title'], missing_before=missing,
                      applied=args.apply and result['status'] != 'error' and not result.get('cover', '').startswith('error'))
        return key, result
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(process, target) for target in targets]
        for i, future in enumerate(as_completed(futures), 1):
            key, result = future.result()
            report[key] = result
            write_json(REPORT, report)
            if args.apply:
                write_json(manifest_path, manifest.copy())
            print(f'[{i}/{len(targets)}] {result["status"]}: {result["title"]} ({result.get("cover", result.get("reason", ""))})', flush=True)
    # The splitter consumes these URLs for episode and overview covers. Keep
    # source identities unchanged so public routes and episode grouping survive.
    if args.apply:
        by_key = {}
        for path in (ROOT / 'data/books').glob('*.json'):
            book = json.loads(path.read_text(encoding='utf-8'))
            if valid_isbn13(book.get('isbn13', '')) and (book.get('bibliotheek_url') or book.get('openlibrary_work') or book.get('book_repair_alias_of')):
                converted = isbn10_from_isbn13(book.get('isbn13', ''))
                if converted != book.get('isbn10', ''):
                    book['isbn10'] = converted
                    write_json(path, book)
            if (book.get('bibliotheek_url') or book.get('book_repair_alias_of')) and book.get('thumbnail'):
                by_key[book['key']] = book
                if book.get('volume_id'):
                    by_key['vol-' + book['volume_id']] = book
                if book.get('isbn13'):
                    by_key[book['isbn13']] = book
        for path in (ROOT / 'data/analysis').glob('*.json'):
            analysis = json.loads(path.read_text(encoding='utf-8'))
            changed = False
            for book in analysis.get('books', []):
                key = book.get('isbn13') or ('vol-' + book['volume_id'] if book.get('volume_id') else
                                            slug(book.get('canonical_title') or book.get('title', '')))
                if key in by_key and book.get('thumbnail') != by_key[key]['thumbnail']:
                    book['thumbnail'] = by_key[key]['thumbnail']
                    changed = True
            if changed:
                write_json(path, analysis)
    from collections import Counter
    print(dict(Counter(r['status'] for r in report.values())), flush=True)


if __name__ == '__main__':
    main()
