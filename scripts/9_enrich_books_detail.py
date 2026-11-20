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

ROOT         = pathlib.Path(__file__).resolve().parent.parent
DIR_ANALYSIS = ROOT / 'data' / 'analysis'
DIR_BOOKS    = ROOT / 'data' / 'books'

GOOGLE_BOOKS_URL = 'https://www.googleapis.com/books/v1/volumes'
BOOKS_DELAY = 0.2  # seconds between Google Books API calls


# ---------------------------------------------------------------------------
# Google Books helpers
# ---------------------------------------------------------------------------

def _fix_thumbnail(url: str) -> str:
    """Force HTTPS and strip curl parameters."""
    if not url:
        return ''
    url = url.replace('http://', 'https://')
    url = re.sub(r'&?zoom=\d+', '', url)
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
                return None
        except Exception as exc:
            print(f'    Error fetching volume {volume_id}: {exc}')
            return None
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
        return None


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

    return {
        'key': key,
        'isbn13': isbn13,
        'isbn10': isbn10,
        'volume_id': volume_id,
        'title': canonical_title or vi.get('title', ''),
        'subtitle': vi.get('subtitle', ''),
        'author': author,
        'description': (vi.get('description', '') or '')[:2000],
        'thumbnail': thumbnail,
        'thumbnail_large': thumbnail_large,
        'publisher': vi.get('publisher', ''),
        'published_year': (vi.get('publishedDate', '') or '')[:4],
        'page_count': vi.get('pageCount') or 0,
        'language': vi.get('language', ''),
        'categories': vi.get('categories', []),
        'google_books_url': vi.get('infoLink', '') or
                            f'https://books.google.nl/books?id={volume_id}',
    }


# ---------------------------------------------------------------------------
# Collect unique books from all analysis files
# ---------------------------------------------------------------------------

def _collect_unique_books() -> dict[str, dict]:
    """Scan all analysis files and return unique books keyed by book_key."""
    books: dict[str, dict] = {}
    for f in sorted(DIR_ANALYSIS.glob('*.json')):
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
    keys = []
    for key in all_books:
        if force or not (DIR_BOOKS / f'{key}.json').exists():
            keys.append(key)
    return keys


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

    all_books = _collect_unique_books()
    if not all_books:
        sys.exit('No books with identifiers found in data/analysis/*.json')

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
