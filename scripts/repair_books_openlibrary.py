"""One-time, resumable Open Library repair of missing book details and covers.

Run from the repository root with .venv/Scripts/python.exe. Use --apply to
write repairs; without it, only the JSON report and temporary API cache change.
Existing route keys and Google volume IDs are preserved. No paid APIs are used.
"""
import argparse
import hashlib
from functools import lru_cache
import io
import json
import os
import pathlib
import re
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

from PIL import Image, ImageChops, ImageStat
import requests

from book_covers import aliases, normalize_image
from utils import slug

ROOT = pathlib.Path(__file__).resolve().parents[1]
CACHE = pathlib.Path(tempfile.gettempdir()) / 'ongelooflijk-openlibrary-repair'
REPORT = ROOT / 'data/book_repair_report.json'
HEADERS = {'User-Agent': 'OngelooflijkArchief/1.0 (one-time metadata repair)',
           'Accept': 'application/json'}


def write_json(path, value):
    """Publish complete JSON files; tolerate transient Windows file locks."""
    temporary = path.with_name('.' + path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
    payload = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    for attempt in range(6):
        try:
            temporary.write_text(payload, encoding='utf-8')
            temporary.replace(path)
            return
        except OSError:
            if attempt == 5:
                raise
            time.sleep(.25 * (attempt + 1))


def norm(value):
    value = unicodedata.normalize('NFKD', value or '').casefold()
    value = ''.join(c for c in value if not unicodedata.combining(c)).replace('ø', 'o').replace('ł', 'l')
    return ' '.join(re.findall(r'[a-z0-9]+', value))


def valid_isbn13(value):
    return bool(re.fullmatch(r'97[89]\d{10}', value or '')) and sum(
        int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(value)) % 10 == 0


def isbn10_from_isbn13(value):
    if not valid_isbn13(value) or not value.startswith('978'):
        return ''
    body = value[3:12]
    check = (-sum(int(digit) * (10 - index) for index, digit in enumerate(body))) % 11
    return body + ('X' if check == 10 else str(check))


def catalogue_isbn13(value):
    values = re.findall(r'\b[\dXx]{10,13}\b', value or '')
    for isbn in values:
        if valid_isbn13(isbn):
            return isbn
    for isbn in values:
        if len(isbn) != 10 or not isbn[:9].isdigit() or not (isbn[-1].isdigit() or isbn[-1].upper() == 'X'):
            continue
        digits = [int(d) for d in isbn[:9]] + [10 if isbn[-1].upper() == 'X' else int(isbn[-1])]
        if sum(d * (10 - i) for i, d in enumerate(digits)) % 11:
            continue
        body = '978' + isbn[:9]
        return body + str((-sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(body))) % 10)
    return ''


def title_score(left, right):
    def words(value):
        normalized = re.sub(r'^(?:(?:the|a|an|de|het|een|t)\s+)+', '', norm(value))
        return normalized.split(' ')
    left, right = words(left), words(right)
    a, b = ' '.join(left), ' '.join(right)
    if a == b:
        return 1.0
    # Subtitles are frequently absent from the podcast's recommended title.
    if min(len(left), len(right)) >= 2 and (a.startswith(b + ' ') or b.startswith(a + ' ')):
        return .96
    return SequenceMatcher(None, a, b).ratio()


_CLASSICAL_AUTHORS = {
    'augustine': ('Augustinus', 'Aurelius Augustinus', 'Augustinus Aurelius', 'Augustine', 'Saint Augustine', 'Augustine of Hippo', 'Saint Augustine of Hippo'),
    'plato': ('Plato', 'Platon'),
    'aristotle': ('Aristoteles', 'Aristotle'),
    'cicero': ('Cicero', 'Marcus Tullius Cicero', 'M. Tullius Cicero'),
    'seneca': ('Seneca', 'Lucius Annaeus Seneca'),
    'aurelius': ('Marcus Aurelius', 'Marcus Aurelius Antoninus'),
    'boethius': ('Boethius', 'Anicius Manlius Severinus Boethius'),
    'aquinas': ('Thomas van Aquino', 'Thomas de Aquino', 'Thomas Aquinas'),
    'kempis': ('Thomas a Kempis', 'Thomas Kempis', 'Thomas à Kempis'),
    'erasmus': ('Erasmus', 'Desiderius Erasmus', 'Erasmus van Rotterdam', 'Desiderius Erasmus Roterodamus'),
    'spinoza': ('Spinoza', 'Baruch Spinoza', 'Benedictus de Spinoza', 'Benedict de Spinoza', 'Benedictus Spinoza'),
    'pascal': ('Blaise Pascal', 'Pascal'),
    'dante': ('Dante', 'Dante Alighieri'),
    'milton': ('John Milton',),
    'machiavelli': ('Machiavelli', 'Niccolò Machiavelli'),
    'calvin': ('Johannes Calvijn', 'John Calvin', 'Jean Calvin', 'Johannes Calvinus'),
    'luther': ('Maarten Luther', 'Martin Luther'),
    'montesquieu': ('Montesquieu', 'Charles de Montesquieu'),
    'rousseau': ('Jean-Jacques Rousseau', 'Rousseau'),
    'kant': ('Immanuel Kant',),
    'hegel': ('Georg Wilhelm Friedrich Hegel', 'G. W. F. Hegel', 'Hegel'),
}


@lru_cache(maxsize=4096)
def classical_author(author):
    name = norm(re.split(r',|;', author or '')[0])
    return next((key for key, names in _CLASSICAL_AUTHORS.items() if name in {norm(n) for n in names}), '')


def dutch_lookup_title(title, author):
    """Established translated work titles, never inferred from subject keywords."""
    name, work = classical_author(author), norm(title)
    if name == 'augustine':
        for words, dutch in [
            (('confession', 'belijdenis', 'bekentenis'), 'Belijdenissen'),
            (('civitate', 'city of god', 'stad gods', 'stad van god'), 'De stad van God'),
            (('trinitate', 'trinity', 'drie eenheid'), 'De drie-eenheid'),
            (('beata vita', 'happy life', 'gelukkige leven'), 'Het gelukkige leven'),
        ]:
            if any(word in work for word in words):
                return dutch
    if name == 'kempis' and any(word in work for word in ('navolging', 'imitation', 'imitatio')):
        return 'De navolging van Christus'
    if name == 'plato' and any(word in work for word in ('republiek', 'republic', 'politeia', 'de staat')):
        return 'De staat'
    if name == 'cicero' and ('officiis' in work or 'duties' in work or work in {'de plichten', 'over de plichten', 'plichten'}):
        return 'De plichten'
    if name == 'erasmus' and any(word in work for word in ('lof der zotheid', 'praise of folly', 'stultitiae')):
        return 'Lof der zotheid'
    if name == 'dante' and any(word in work for word in ('commedia', 'divine comedy', 'goddelijke komedie')):
        return 'De goddelijke komedie'
    if name == 'pascal' and ('pensees' in work or 'gedachten' in work):
        return 'Gedachten'
    if name == 'milton' and ('paradise lost' in work or 'paradijs verloren' in work):
        return 'Het paradijs verloren'
    return title


def publisher_matches(expected, edition):
    expected = norm(expected).replace(' ', '')
    return bool(expected) and any(expected in norm(p).replace(' ', '') or
                                 norm(p).replace(' ', '') in expected for p in edition.get('publishers', []))


def edition_score(edition, title, publisher=''):
    physical = (edition.get('physical_format') or '').lower()
    digital = any(word in physical for word in ('ebook', 'e-book', 'electronic', 'audio'))
    has_cover = any(c > 0 for c in edition.get('covers', []))
    return (title_score(title, edition.get('title', '')) >= .90, not digital,
            bool(edition.get('isbn_13')) and has_cover, publisher_matches(publisher, edition),
            bool(edition.get('isbn_13')), has_cover, bool(edition.get('number_of_pages')),
            title_score(title, edition.get('title', '')))


def author_matches(expected, authors):
    if not expected:
        return False  # Do not guess a work from its title alone.
    parts = re.split(r',|;|\s&\s|\s(?:and|en)\s', expected)
    if len(parts) > 1:
        return any(author_matches(part.strip(), authors) for part in parts if part.strip())
    identity = classical_author(expected)
    if identity and any(classical_author(author) == identity for author in authors):
        return True
    expected_words = set(norm(expected).split()) - {'van', 'de', 'der', 'den', 'von'}
    surname = norm(expected).split()[-1]
    expected_given = [w for w in norm(expected).split()[:-1] if w not in {'van', 'de', 'der', 'den', 'von'}]
    for author in authors:
        words = norm(author).split()
        if surname not in words:
            continue
        if len(expected_words & set(words)) >= min(2, len(expected_words)):
            return True
        index = words.index(surname)
        given = words[:index] if index else words[1:]
        given = [w for w in given if w not in {'van', 'de', 'der', 'den', 'von'}]
        if given and expected_given and all(a == b or (a[0] == b[0] and min(len(a), len(b)) == 1)
                                          for a, b in zip(expected_given, given)):
            return True
    return False


def language_preference(title, record):
    if classical_author(record.get('author')):
        return 'dut'
    words = set(norm(title).split())
    if words & {'ethica', 'officiis', 'summa', 'confessiones', 'meditationes', 'republica', 'metaphysica', 'tractatus',
                'phaedrus', 'sancti', 'retractationum', 'im', 'nichts'}:
        return 'dut'
    if words & {'de', 'het', 'een', 'van', 'voor', 'over', 'zijn', 'mijn', 'onze', 'geloof', 'godsdienst'}:
        return 'dut'
    if words & {'the', 'a', 'an', 'of', 'and', 'how', 'why', 'with', 'confessions'}:
        return 'eng'
    if record.get('language') == 'en':
        return 'eng'
    # Older works with an ambiguous title prefer a Dutch edition. Explicit
    # English recommended titles above always keep their English edition.
    return 'dut'


class Client:
    def __init__(self, direct=False):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if direct else urllib.request.build_opener()
        self.last_request = 0
        self.request_lock = threading.Lock()
        self.isbn_details = {}
        self.direct = direct
        self.sessions = threading.local()

    def get(self, url, binary=False):
        path = CACHE / (hashlib.sha256(url.encode()).hexdigest() + ('.img' if binary else '.json'))
        if path.exists():
            payload = path.read_bytes()
            return payload if binary else json.loads(payload)
        for attempt in range(3):
            with self.request_lock:
                time.sleep(max(0, 1.05 - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
            try:
                if not hasattr(self.sessions, 'session'):
                    self.sessions.session = requests.Session()
                    self.sessions.session.trust_env = not self.direct
                with self.sessions.session.get(url, headers={**HEADERS, 'Accept': 'image/*' if binary else 'application/json'},
                                               timeout=(6, 12), stream=True) as response:
                    if response.status_code == 404:
                        return None
                    if response.status_code >= 400:
                        raise urllib.error.HTTPError(url, response.status_code, response.reason, {}, None)
                    payload = b''
                    for chunk in response.iter_content(65536):
                        payload += chunk
                        if len(payload) > 8 * 1024 * 1024:
                            raise ValueError('response exceeds size limit')
                if len(payload) > 8 * 1024 * 1024:
                    raise ValueError('response exceeds size limit')
                result = payload if binary else json.loads(payload)
                path.write_bytes(payload)
                return result
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        return None

    def api(self, path, **params):
        if path.startswith('/isbn/') and path[6:-5] in self.isbn_details:
            return self.isbn_details[path[6:-5]]
        return self.get('https://openlibrary.org' + path + ('?' + urllib.parse.urlencode(params) if params else ''))

    def prefetch_isbns(self, records):
        isbns = sorted({r.get('isbn13') or r.get('isbn10') for r in records} - {None, ''})
        for offset in range(0, len(isbns), 25):
            batch = isbns[offset:offset + 25]
            try:
                data = self.api('/api/books', bibkeys=','.join('ISBN:' + i for i in batch), jscmd='details', format='json')
                self.isbn_details.update({i: (data or {}).get('ISBN:' + i, {}).get('details') for i in batch})
                print(f'ISBN metadata fetched: {min(offset + 25, len(isbns))}/{len(isbns)}', flush=True)
            except (OSError, ValueError, requests.RequestException) as exc:
                print(f'ISBN batch deferred to individual lookups: {type(exc).__name__}', flush=True)


def confident_candidates(client, title, author, docs):
    matches = []
    for doc in docs:
        titles = [doc.get('title', '')] + [e.get('title', '') for e in doc.get('editions', {}).get('docs', [])]
        matched_title = max(titles, key=lambda t: title_score(title, t))
        if title_score(title, matched_title) < .90:
            continue
        names = list(doc.get('author_name', []))
        if author and not author_matches(author, names):
            for key in doc.get('author_key', [])[:2]:
                data = client.api('/authors/' + key + '.json') or {}
                names += [data.get('name', '')] + data.get('alternate_names', [])
        if author_matches(author, names):
            doc['_matched_title'] = matched_title
            matches.append(doc)
    return matches


def placeholder(image, reference):
    if reference is None:
        return False
    sample = image.convert('RGB').resize((32, 40))
    return sum(ImageStat.Stat(ImageChops.difference(sample, reference)).mean) / 3 < 4


def valid_cover(path, reference):
    try:
        normalize_image(path.read_bytes())
        with Image.open(path) as image:
            return not placeholder(image, reference)
    except (OSError, ValueError):
        return False


def collect_targets(manifest, reference):
    records, volumes = {}, {}
    for path in sorted((ROOT / 'data/books').glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        records[path.stem] = (path, record)
        if record.get('volume_id'):
            volumes[record['volume_id']] = path.stem
    targets = dict(records)
    for path in sorted((ROOT / 'data/analysis').glob('*.json')):
        for book in json.loads(path.read_text(encoding='utf-8')).get('books', []):
            title = book.get('canonical_title') or book.get('title', '')
            if not title:
                continue
            vid = book.get('volume_id') or ''
            key = book.get('isbn13') or volumes.get(vid) or ('vol-' + vid if vid else slug(title))
            if key not in targets:
                record = dict(key=key, title=title, author=book.get('canonical_author') or book.get('author', ''),
                              isbn13=book.get('isbn13') or '', isbn10=book.get('isbn10') or '', volume_id=vid,
                              description='', thumbnail='', thumbnail_large='', publisher='', published_year='',
                              page_count=0, language='', categories=[], google_books_url='', is_ebook=False)
                targets[key] = (ROOT / 'data/books' / (key + '.json'), record)
            targets[key][1].setdefault('recommended_title', book.get('title') or title)
            targets[key][1].setdefault('recommended_author', book.get('author') or book.get('canonical_author') or targets[key][1].get('author', ''))
    result = []
    for key, (path, record) in targets.items():
        identity = aliases(record.get('isbn13'), record.get('volume_id'), record.get('thumbnail'))
        has_cover = any(valid_cover(ROOT / 'data/book_covers' / manifest[a]['file'], reference)
                        for a in identity if manifest.get(a, {}).get('file'))
        missing = [f for f in ('description', 'isbn13', 'publisher', 'published_year', 'page_count') if not record.get(f)]
        if not has_cover:
            missing.append('cover')
        if record.get('openlibrary_match') == 'work-only' and 'covers.openlibrary.org' in record.get('thumbnail', '') and language_preference(
                record.get('recommended_title') or record['title'], record) == 'dut':
            missing.append('unverified_edition_cover')
        if classical_author(record.get('author')) and (record.get('language') != 'nl' or
                not str(record.get('published_year', '')).isdigit() or int(record['published_year']) < 1950):
            missing.append('modern_dutch_edition')
        if missing:
            result.append((key, path, record, missing))
    return result


def resolve(client, record):
    isbn = record.get('isbn13') or record.get('isbn10')
    edition = client.api('/isbn/' + urllib.parse.quote(isbn) + '.json') if isbn else None
    if edition and edition.get('works'):
        work_key = edition['works'][0]['key']
        work = client.api(work_key + '.json') if not record.get('description') else {'key': work_key}
        recommended = record.get('recommended_title') or record['title']
        # Dutch or classical titles can have been matched to a foreign ISBN by
        # Google. Check Dutch editions before retaining that foreign edition.
        if language_preference(recommended, record) != 'dut' or any(
                l.get('key') == '/languages/dut' for l in edition.get('languages', [])):
            return edition, work, 'isbn'
        for offset in range(0, 400, 100):
            page = client.api(work_key + '/editions.json', limit=100, offset=offset)
            entries = (page or {}).get('entries', [])
            dutch = [e for e in entries if any(l.get('key') == '/languages/dut' for l in e.get('languages', []))]
            if dutch:
                selected = max(dutch, key=lambda e: (bool(e.get('isbn_13')), bool(e.get('covers')), bool(e.get('number_of_pages'))))
                return selected, work, 'dutch-edition-preferred'
            if len(entries) < 100:
                break
        return edition, work, 'isbn-no-dutch-edition'
    def search(title):
        # A quoted phrase also searches translated edition titles. Restricting
        # author by surname tolerates catalogue initials; verify the full name
        # (or compatible initials/author aliases) independently afterwards.
        query = 'title:' + json.dumps(title, ensure_ascii=False)
        if record.get('author'):
            primary_author = re.split(r',|;|\s&\s|\s(?:and|en)\s', record['author'])[0]
            query += ' author:' + json.dumps(norm(primary_author).split()[-1])
        return client.api('/search.json', q=query, limit=8,
                          fields='key,title,author_name,author_key,first_publish_year,editions,editions.title,editions.key')
    search_title = record.get('recommended_title') or record['title']
    result = search(search_title)
    candidates = confident_candidates(client, search_title, record.get('author'), (result or {}).get('docs', []))
    primary_title = re.split(r':|\s[–—]\s', search_title, maxsplit=1)[0]
    if not candidates and primary_title != search_title:
        result = search(primary_title)
        candidates = confident_candidates(client, primary_title, record.get('author'), (result or {}).get('docs', []))
        search_title = primary_title
    if not candidates:
        return None, None, 'no confident title/author match'
    candidates.sort(key=lambda d: title_score(search_title, d.get('_matched_title', d['title'])), reverse=True)
    if len(candidates) > 1 and norm(candidates[0].get('_matched_title', candidates[0]['title'])) != norm(
            candidates[1].get('_matched_title', candidates[1]['title'])) and abs(
            title_score(search_title, candidates[0].get('_matched_title', candidates[0]['title'])) -
            title_score(search_title, candidates[1].get('_matched_title', candidates[1]['title']))) < .03:
        return None, None, 'ambiguous works'
    work_key = candidates[0]['key']
    work = client.api(work_key + '.json')
    editions = []
    for entry in candidates[0].get('editions', {}).get('docs', []):
        if title_score(search_title, entry.get('title', '')) >= .90:
            matched_edition = client.api(entry['key'] + '.json')
            if matched_edition:
                editions.append(matched_edition)
    preferred = language_preference(record.get('recommended_title') or record['title'], record)
    # Pagination matters especially for older books with many translations.
    for offset in range(0, 400, 100):
        page = client.api(work_key + '/editions.json', limit=100, offset=offset)
        entries = (page or {}).get('entries', [])
        editions.extend(entries)
        if len(entries) < 100 or any(e.get('isbn_13') and any(c > 0 for c in e.get('covers', [])) and any(
                l.get('key') == '/languages/' + preferred for l in e.get('languages', [])) and
                (preferred == 'dut' or not record.get('publisher') or publisher_matches(record['publisher'], e))
                for e in editions):
            break
    if isbn:
        exact = [e for e in editions if isbn in e.get('isbn_13', []) + e.get('isbn_10', [])]
        # A work-level match does not prove the existing ISBN's edition details.
        if exact:
            return exact[0], work, 'isbn-in-work'
        dutch = [e for e in editions if any(l.get('key') == '/languages/dut' for l in e.get('languages', []))]
        if preferred == 'dut' and dutch:
            return max(dutch, key=lambda e: (bool(e.get('isbn_13')), bool(e.get('covers')))), work, 'dutch-edition-preferred'
        return None, work, 'work-only'
    preferred_editions = [e for e in editions if any(l.get('key') == '/languages/' + preferred for l in e.get('languages', []))]
    if preferred_editions:
        editions = preferred_editions
    else:
        # When language metadata is absent, retain the recommended title.
        editions = [e for e in editions if not e.get('languages') and preferred == 'eng'
                    and title_score(record['title'], e.get('title', '')) >= .90]
    if not editions:
        return None, work, 'work-only'
    return max(editions, key=lambda e: edition_score(e, record['title'], record.get('publisher', ''))), work, 'title-author-' + preferred


def repair(client, record, missing, manifest, reference, apply):
    edition, work, match = resolve(client, record)
    if not work:
        return {'status': 'unresolved', 'reason': match}
    if not edition and language_preference(record.get('recommended_title') or record['title'], record) == 'dut':
        return {'status': 'unresolved', 'reason': 'no verified Dutch edition'}
    updated = dict(record)
    description = (edition or {}).get('description') or work.get('description')
    if isinstance(description, dict):
        description = description.get('value', '')
    if not updated.get('description') and description:
        # Stored descriptions are HTML; encode provider prose as plain text.
        import html
        updated['description'] = html.escape(description)
    if edition:
        newly_identified = not record.get('isbn13') or match == 'dutch-edition-preferred'
        fields = {'isbn13': next((i for i in edition.get('isbn_13', []) if re.fullmatch(r'\d{13}', i)), ''),
                  'isbn10': next(iter(edition.get('isbn_10', [])), ''),
                  'publisher': ', '.join(edition.get('publishers', [])),
                  'published_year': next(iter(re.findall(r'\b(?:1[4-9]|20)\d{2}\b', edition.get('publish_date', ''))), ''),
                  'page_count': edition.get('number_of_pages') or 0,
                  'language': {'dut': 'nl', 'eng': 'en'}.get(next((l['key'].rsplit('/', 1)[-1] for l in edition.get('languages', [])), ''), '')}
        for field, value in fields.items():
            if (value and not updated.get(field)) or newly_identified:
                updated[field] = value
        if match in ('dutch-edition-preferred', 'title-author-dut'):
            updated['title'] = edition['title']
        physical_format = (edition.get('physical_format') or '').lower()
        if physical_format:
            updated['is_ebook'] = any(word in physical_format for word in ('ebook', 'e-book', 'electronic'))
        updated['openlibrary_edition'] = edition['key']
    updated['openlibrary_work'] = work['key']
    updated['openlibrary_match'] = match
    cover_status = 'existing'
    if 'cover' in missing:
        cover_status = 'unavailable'
        cover_ids = [c for c in ((edition or {}).get('covers') or ([] if edition else work.get('covers', []))) if c > 0]
        cover_candidates = [f'https://covers.openlibrary.org/b/id/{c}-L.jpg?default=false' for c in cover_ids[:3]]
        if not cover_candidates and updated.get('isbn13'):
            cover_candidates.append(f'https://covers.openlibrary.org/b/isbn/{updated["isbn13"]}-L.jpg?default=false')
        for url in cover_candidates:
            try:
                payload = client.get(url, binary=True)
                if not payload:
                    continue
                payload = normalize_image(payload)
                with Image.open(io.BytesIO(payload)) as image:
                    if placeholder(image, reference):
                        continue
                original_isbn = record.get('isbn13') or (record['key'] if re.fullmatch(r'\d{13}', record['key']) else '')
                identity = aliases(updated.get('isbn13'), updated.get('volume_id'), url) + aliases(original_isbn)
                filename = hashlib.sha256(('openlibrary:' + record['key']).encode()).hexdigest()[:24] + '.jpg'
                if apply:
                    (ROOT / 'data/book_covers' / filename).write_bytes(payload)
                    for alias in identity + aliases(thumbnail=updated.get('thumbnail')) + aliases(thumbnail=updated.get('thumbnail_large')):
                        manifest[alias] = {'file': filename, 'source_url': url}
                updated['thumbnail'] = updated['thumbnail_large'] = url
                cover_status = 'downloaded'
                break
            except (OSError, ValueError, requests.RequestException):
                continue
    changes = [f for f in updated if updated[f] != record.get(f)]
    if apply and changes:
        write_json(ROOT / 'data/books' / (record['key'] + '.json'), updated)
    return dict(status='repaired' if changes else 'unchanged', match=match, work=work['key'],
                edition=(edition or {}).get('key'), changed=changes, cover=cover_status,
                still_missing=[f for f in ('description', 'isbn13', 'publisher', 'published_year', 'page_count') if not updated.get(f)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--direct', action='store_true', help='Use direct HTTPS instead of environment proxies')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--key', help='Repair a single existing route key')
    parser.add_argument('--retry-unresolved', action='store_true', help='Retry unresolved title/author searches')
    parser.add_argument('--cover-fallback', action='store_true', help='Find another English edition when the existing edition has no usable cover')
    parser.add_argument('--title-first', action='store_true', help='Resolve missing metadata by title and author, using the old ISBN only as provenance')
    args = parser.parse_args()
    manifest_path = ROOT / 'data/book_covers/index.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    reference_path = ROOT / 'data/book_covers/a0fb7fe96c499d4e7c090478.jpg'
    with Image.open(reference_path) as image:
        reference = image.convert('RGB').resize((32, 40))
    client = Client(args.direct)
    targets = collect_targets(manifest, reference)
    if args.cover_fallback:
        targets = [t for t in targets if 'cover' in t[3] and
                   language_preference(t[2].get('recommended_title') or t[2]['title'], t[2]) == 'eng']
    if args.key:
        targets = [t for t in targets if t[0] == args.key]
    if args.limit:
        targets = targets[:args.limit]
    report_path = (ROOT / 'data/book_repair_edition_report.json' if args.cover_fallback else
                   ROOT / 'data/book_repair_title_report.json' if args.title_first else REPORT)
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    print(f'{len(targets)} books need metadata or cover repairs', flush=True)
    def process(target):
        key, path, record, missing = target
        record = dict(record, author=record.get('recommended_author') or record.get('author', ''))
        try:
            if (args.cover_fallback or args.title_first) and record.get('isbn13'):
                record = dict(record, original_isbn13=record.get('original_isbn13') or record['isbn13'],
                              isbn13='', isbn10='', publisher='')
            result = repair(client, record, missing, manifest, reference, args.apply)
        except Exception as exc:
            result = {'status': 'error', 'reason': f'{type(exc).__name__}: {exc}'}
        result.update(title=record['title'], missing_before=missing, applied=args.apply and result['status'] != 'error')
        return key, result
    pending = [t for t in targets if not (args.apply and report.get(t[0], {}).get('applied') and not args.key
               and not (args.retry_unresolved and report[t[0]].get('status') == 'unresolved'))]
    client.prefetch_isbns([t[2] for t in pending])
    # Overlap network latency while retaining a global limit of one API request
    # per second. Metadata and cover requests use the same limiter.
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(process, target) for target in pending]
        for i, job in enumerate(as_completed(jobs), 1):
            key, result = job.result()
            report[key] = result
            write_json(report_path, report)
            if args.apply:
                write_json(manifest_path, manifest.copy())
            print(f'[{i}/{len(pending)}] {result["status"]}: {result["title"]} ({result.get("match", result.get("reason", ""))})', flush=True)
    from collections import Counter
    print(dict(Counter(r['status'] for r in report.values())), flush=True)

    if args.apply:
        # Stop publishing the recognized Google placeholder for unresolved books.
        # Keep physical cache files intact; other local work may still use them.
        invalid_files = {entry['file'] for entry in manifest.values() if entry.get('file')
                         and not valid_cover(ROOT / 'data/book_covers' / entry['file'], reference)}
        manifest = {key: entry for key, entry in manifest.items() if entry.get('file') not in invalid_files}
        write_json(manifest_path, manifest)
        # Keep analysis identities (and therefore public URLs) unchanged, but
        # make the repaired cover available to episode and overview renderers.
        by_key = {}
        for path in (ROOT / 'data/books').glob('*.json'):
            book = json.loads(path.read_text(encoding='utf-8'))
            if book.get('openlibrary_work') and book.get('thumbnail'):
                for key in (book['key'], book.get('isbn13'),
                            'vol-' + book['volume_id'] if book.get('volume_id') else ''):
                    if key:
                        by_key[key] = book
        for path in (ROOT / 'data/analysis').glob('*.json'):
            analysis = json.loads(path.read_text(encoding='utf-8'))
            changed = False
            for book in analysis.get('books', []):
                key = book.get('isbn13') or ('vol-' + book['volume_id'] if book.get('volume_id') else
                                            slug(book.get('canonical_title') or book.get('title', '')))
                detail = by_key.get(key)
                if detail and book.get('thumbnail') != detail['thumbnail']:
                    book['thumbnail'] = detail['thumbnail']
                    changed = True
            if changed:
                write_json(path, analysis)


if __name__ == '__main__':
    main()
