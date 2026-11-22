"""Enrich unique books from analysis files with full Google Books detail records.

For each unique book found in `data/analysis/*.json` (identified by isbn13 or volume_id),
this script fetches the full Google Books volume record and writes it to
`data/books/{key}.json`. The site then serves these files at `data/books/{key}.json`
for the book detail page (#b-{key}).

Book key: isbn13 if available, else `vol-{volume_id}`.

Usage:
    python scripts/9_enrich_books_detail.py --all-missing
    python scripts/9_enrich_books_detail.py --all-missing --force
    python scripts/9_enrich_books_detail.py --isbn 9789028282384
    python scripts/9_enrich_books_detail.py --volume-id YqbdxgEACAAJ

Requires:
    GOOGLE_BOOKS_API_KEY env var (optional; improves rate limits)
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.parse, urllib.error
import pathlib
from html.parser import HTMLParser

# Tags we keep from Google Books HTML descriptions; everything else is stripped
# (but its text content is kept).
_SAFE_TAGS = {'p', 'br', 'b', 'i', 'em', 'strong', 'ul', 'li'}


class _SafeHtmlParser(HTMLParser):
    """Strip all HTML except _SAFE_TAGS (no attributes kept)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SAFE_TAGS:
            self._parts.append(f'<{tag}>')

    def handle_endtag(self, tag):
        if tag in _SAFE_TAGS and tag != 'br':
            self._parts.append(f'</{tag}>')

    def handle_data(self, data):
        self._parts.append(
            data.replace('&', '&amp;').replace('<', '&lt;')
                .replace('>', '&gt;').replace('"', '&quot;')
        )

    def result(self) -> str:
        return ''.join(self._parts).strip()


def _sanitize_description(html: str) -> str:
    """Return *html* with only safe tags kept (all attributes stripped)."""
    if not html:
        return ''
    p = _SafeHtmlParser()
    p.feed(html)
    return p.result()


ROOT         = pathlib.Path(__file__).resolve().parent.parent
DIR_ANALYSIS = ROOT / 'data' / 'analysis'
DIR_BOOKS    = ROOT / 'data' / 'books'

GOOGLE_BOOKS_URL = 'https://www.googleapis.com/books/v1/volumes'
BOOKS_DELAY = 0.2  # seconds between Google Books API calls


# ---------------------------------------------------------------------------
# Google Books helpers
# ---------------------------------------------------------------------------

def _fix_thumbnail(url: str) -> str:
    """Force HTTPS and normalise to a stable, token-free URL.

    Google's API returns thumbnail URLs with a time-limited imgtk= signed token
    that expires within hours. Stripping it (and the source= param) leaves a
    stable public URL that works as long as the book has a public cover.
    """
    if not url:
        return ''
    url = url.replace('http://', 'https://')
    url = re.sub(r'&?zoom=\d+', '', url)
    url = re.sub(r'&?imgtk=[^&]+', '', url)
    url = re.sub(r'&?source=[^&]+', '', url)
    return url.strip('&?')


def _fetch_book_by_volume_id(volume_id: str, api_key: str = '') -> dict | None:
    """Fetch the full Google Books volume record by volume_id."""
    params = {}
    if api_key:
        params['key'] = api_key
    url = f'{GOOGLE_BOOKS_URL}/{urllib.parse.quote(volume_id)}'
    if params:
        url += '?' + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                wait = 10 * (attempt + 1)
                print(f'    429 — waiting {wait}s …')
                time.sleep(wait)
            elif exc.code == 404:
                return None
            else:
                print(f'    HTTP {exc.code} for volume {volume_id}')
                raise
        except Exception as exc:
            print(f'    Error fetching volume {volume_id}: {exc}')
            raise
    return None


def _fetch_book_by_isbn(isbn13: str, api_key: str = '') -> dict | None:
    """Search Google Books by ISBN-13 and return the best matching volume."""
    params = {'q': f'isbn:{isbn13}', 'maxResults': '1', 'printType': 'books'}
    if api_key:
        params['key'] = api_key
    url = GOOGLE_BOOKS_URL + '?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            data = json.loads(r.read().decode('utf-8'))
        items = data.get('items', [])
        return items[0] if items else None
    except Exception as exc:
        print(f'    Error searching ISBN {isbn13}: {exc}')
        raise


def _build_book_record(volume_id: str, volume_data: dict,
                       canonical_title: str = '', canonical_author: str = '',
                       isbn13_hint: str = '', isbn10_hint: str = '') -> dict:
    """Build a normalised book record from a Google Books volume response."""
    vi = volume_data.get('volumeInfo', {})
    ids = {x['type']: x['identifier'] for x in vi.get('industryIdentifiers', [])}
    isbn13 = ids.get('ISBN_13') or isbn13_hint or ''
    isbn10 = ids.get('ISBN_10') or isbn10_hint or ''

    # Key = isbn13 if we have one, else vol-{volume_id}
    key = isbn13 if isbn13 else f'vol-{volume_id}'

    # Prefer larger thumbnail
    image_links = vi.get('imageLinks', {})
    thumbnail = _fix_thumbnail(
        image_links.get('thumbnail') or image_links.get('smallThumbnail') or ''
    )
    thumbnail_large = _fix_thumbnail(
        image_links.get('large') or image_links.get('medium') or thumbnail
    )
    # Bump default thumbnail from zoom=1 to zoom=3 for a larger image
    if thumbnail and 'zoom=' not in thumbnail:
        thumbnail_large = thumbnail + ('&' if '?' in thumbnail else '?') + 'zoom=3'

    authors = vi.get('authors', [])
    author = canonical_author or (', '.join(authors) if authors else '')

    # infoLink from Google sometimes points to Play Store instead of Books —
    # play.google.com links are ebook-only and often broken for print books.
    info_link = vi.get('infoLink', '') or ''
    if 'books.google.' not in info_link:
        info_link = f'https://books.google.nl/books?id={volume_id}'

    # Detect ebook-only entries: Play Store URL or epub/pdf available but no print
    sale_info   = volume_data.get('saleInfo', {})
    access_info = volume_data.get('accessInfo', {})
    is_ebook = (
        'play.google.com' in (vi.get('infoLink', '') or '')
        or access_info.get('epub', {}).get('isAvailable', False)
        or access_info.get('pdf', {}).get('isAvailable', False)
    )

    return {
        'key': key,
        'isbn13': isbn13,
        'isbn10': isbn10,
        'volume_id': volume_id,
        'title': canonical_title or vi.get('title', ''),
        'subtitle': vi.get('subtitle', ''),
        'author': author,
        'description': _sanitize_description((vi.get('description', '') or '')[:2000]),
        'thumbnail': thumbnail,
        'thumbnail_large': thumbnail_large,
        'publisher': vi.get('publisher', ''),
        'published_year': (vi.get('publishedDate', '') or '')[:4],
        'page_count': vi.get('pageCount') or 0,
        'language': vi.get('language', ''),
        'categories': vi.get('categories', []),
        'google_books_url': info_link,
        'is_ebook': is_ebook,
    }


# ---------------------------------------------------------------------------
# Collect unique books from all analysis files
# ---------------------------------------------------------------------------

def _collect_unique_books(episode: str | None = None) -> dict[str, dict]:
    """Scan all analysis files and return unique books keyed by book_key."""
    books: dict[str, dict] = {}
    for f in sorted(DIR_ANALYSIS.glob('*.json')):
        if episode is not None and f.stem != episode:
            continue
        try:
            an = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        for b in an.get('books', []):
            isbn13 = (b.get('isbn13') or '').strip()
            volume_id = (b.get('volume_id') or '').strip()
            if not isbn13 and not volume_id:
                continue  # no identifier — cannot enrich
            key = isbn13 if isbn13 else f'vol-{volume_id}'
            if key not in books:
                books[key] = {
                    'key': key,
                    'isbn13': isbn13,
                    'isbn10': (b.get('isbn10') or '').strip(),
                    'volume_id': volume_id,
                    'canonical_title': b.get('canonical_title') or b.get('title', ''),
                    'canonical_author': b.get('canonical_author') or b.get('author', ''),
                }
    return books


def _keys_needing_enrichment(all_books: dict[str, dict], force: bool) -> list[str]:
    # Build a set of volume_ids already covered by an existing book file so that
    # a vol-X key isn't re-fetched just because the enriched file was saved under
    # an isbn13 key after Google Books returned one.
    covered_volume_ids: set[str] = set()
    if not force and DIR_BOOKS.exists():
        for f in DIR_BOOKS.glob('*.json'):
            try:
                vid = json.loads(f.read_text(encoding='utf-8')).get('volume_id', '')
                if vid:
                    covered_volume_ids.add(vid)
            except Exception:
                pass

    keys = []
    for key, meta in all_books.items():
        if force:
            keys.append(key)
        elif (DIR_BOOKS / f'{key}.json').exists():
            pass  # already have it under its own key
        elif meta.get('volume_id') and meta['volume_id'] in covered_volume_ids:
            pass  # already enriched under a different (isbn13) key
        else:
            keys.append(key)
    return keys


# ---------------------------------------------------------------------------
# Dutch-edition fallback search
# ---------------------------------------------------------------------------

def _fetch_book_by_title_nl(title: str, author: str = '', api_key: str = '') -> dict | None:
    """Search Google Books restricted to Dutch and return the best physical-book match."""
    query = f'intitle:{title}'
    if author:
        query += f'+inauthor:{author}'
    params = {'q': query, 'maxResults': '5', 'printType': 'books',
              'langRestrict': 'nl'}
    if api_key:
        params['key'] = api_key
    url = GOOGLE_BOOKS_URL + '?' + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            data = json.loads(r.read().decode('utf-8'))
        for item in data.get('items', []):
            vi  = item.get('volumeInfo', {})
            ai  = item.get('accessInfo', {})
            is_ebook = (
                'play.google.com' in (vi.get('infoLink', '') or '')
                or ai.get('epub', {}).get('isAvailable', False)
            )
            if not is_ebook:
                return item
        # All results were ebooks — return first anyway rather than nothing
        items = data.get('items', [])
        return items[0] if items else None
    except Exception as exc:
        print(f'    Dutch fallback search failed for "{title}": {exc}')
        raise


# ---------------------------------------------------------------------------
# Main enrichment logic
# ---------------------------------------------------------------------------

def enrich_book(key: str, book_meta: dict, api_key: str) -> bool:
    """Fetch Google Books detail for one book and write data/books/{key}.json."""
    out_path = DIR_BOOKS / f'{key}.json'

    volume_id = book_meta.get('volume_id', '')
    isbn13    = book_meta.get('isbn13', '')

    volume_data = None

    # Prefer fetch-by-volume_id (single call, most accurate)
    if volume_id:
        volume_data = _fetch_book_by_volume_id(volume_id, api_key)
        time.sleep(BOOKS_DELAY)

    # Fall back to ISBN search
    if volume_data is None and isbn13:
        item = _fetch_book_by_isbn(isbn13, api_key)
        if item:
            volume_id = volume_id or item.get('id', '')
            volume_data = item
        time.sleep(BOOKS_DELAY)

    if volume_data is None:
        print(f'      – no data found (volume_id={volume_id!r}, isbn13={isbn13!r})')
        return False

    # If the matched edition is not Dutch, try a Dutch-language search as fallback.
    # Only do this when we don't have a specific volume_id from the analysis (i.e. the
    # analyst matched a volume and we trust that choice); when we only have an isbn we
    # accept the first hit regardless.
    vi_lang = (volume_data.get('volumeInfo', {}).get('language') or '')
    if vi_lang != 'nl' and not volume_id and book_meta.get('canonical_title'):
        nl_item = _fetch_book_by_title_nl(
            book_meta['canonical_title'],
            book_meta.get('canonical_author', ''),
            api_key,
        )
        if nl_item:
            print(f'      → Dutch edition found, using that instead')
            volume_id = nl_item.get('id', '') or volume_id
            volume_data = nl_item
        time.sleep(BOOKS_DELAY)

    record = _build_book_record(
        volume_id=volume_id or volume_data.get('id', ''),
        volume_data=volume_data,
        canonical_title=book_meta.get('canonical_title', ''),
        canonical_author=book_meta.get('canonical_author', ''),
        isbn13_hint=isbn13,
        isbn10_hint=book_meta.get('isbn10', ''),
    )

    # If the actual key differs from what we expected (isbn13 discovered via volume lookup),
    # update the key to stay consistent with the record.
    actual_key = record['key']
    out_path = DIR_BOOKS / f'{actual_key}.json'

    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'      ✓ {record["title"]!r} → {out_path.name}')
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Enrich book records with Google Books detail data.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all-missing', action='store_true',
                       help='Enrich all books not yet in data/books/')
    group.add_argument('--episode', help='Enrich missing books from one episode only')
    group.add_argument('--isbn', type=str, metavar='ISBN13',
                       help='Enrich one book by ISBN-13')
    group.add_argument('--volume-id', type=str, metavar='VOLUME_ID',
                       help='Enrich one book by Google Books volume ID')
    parser.add_argument('--force', action='store_true',
                        help='Re-fetch even books that already have a data/books/ file')
    parser.add_argument('--api-key', type=str,
                        help='Google Books API key (overrides GOOGLE_BOOKS_API_KEY env var)')
    args = parser.parse_args()

    # Load .env
    env_path = ROOT / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                os.environ.setdefault(k.strip(), v.strip())

    api_key = args.api_key or os.environ.get('GOOGLE_BOOKS_API_KEY', '')
    if not api_key:
        print('Note: no GOOGLE_BOOKS_API_KEY set — using unauthenticated requests (rate-limited).')

    DIR_BOOKS.mkdir(parents=True, exist_ok=True)

    all_books = _collect_unique_books(args.episode)
    if not all_books:
        print('No books with identifiers to enrich.')
        return

    if args.isbn:
        key = args.isbn.strip()
        meta = all_books.get(key)
        if not meta:
            # Build a minimal meta dict for a manual run
            meta = {'key': key, 'isbn13': key, 'isbn10': '', 'volume_id': '',
                    'canonical_title': '', 'canonical_author': ''}
        to_enrich = [(key, meta)]
    elif args.volume_id:
        vid = args.volume_id.strip()
        key = f'vol-{vid}'
        meta = all_books.get(key)
        if not meta:
            meta = {'key': key, 'isbn13': '', 'isbn10': '', 'volume_id': vid,
                    'canonical_title': '', 'canonical_author': ''}
        to_enrich = [(key, meta)]
    else:
        keys = _keys_needing_enrichment(all_books, args.force)
        to_enrich = [(k, all_books[k]) for k in keys]

    if not to_enrich:
        print('Nothing to enrich.')
        return

    print(f'Enriching {len(to_enrich)} book(s) …')
    ok = 0
    for i, (key, meta) in enumerate(to_enrich, 1):
        print(f'  [{i}/{len(to_enrich)}] {key}  ({meta.get("canonical_title", "?")})')
        if enrich_book(key, meta, api_key):
            ok += 1

    print(f'\nDone: {ok}/{len(to_enrich)} enriched → data/books/')


if __name__ == '__main__':
    main()
