"""Cache book covers locally for the static site.

Run directly to warm data/book_covers/, or let 5b_build_site.py do it at build
time. Reads book details AND analysis, so new episodes need no manual cover step.
Requires Pillow. Failed sources are retried on the next build after 24 hours;
--retry-missing retries them immediately. --offline uses downloaded covers only.
"""
import argparse
import hashlib
import io
import json
import pathlib
import re
import shutil
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageOps

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_BYTES = 8 * 1024 * 1024
RETRY_SECONDS = 24 * 3600
# Average-hash fingerprint of Google's 128x170 "image not available" response.
# It is a valid, sufficiently large image, so dimension checks alone miss it.
_GOOGLE_PLACEHOLDER_HASH = 0xffffffffffffffffc003c001ea7ffc1ff81ffdfff007f007ffffffffffffffff


def clean_url(url):
    """Remove expiring Google tokens and request a practical thumbnail size."""
    parts = urllib.parse.urlsplit(url or '')
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        return ''
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query)
             if k not in ('imgtk', 'source', 'zoom', 'edge')]
    if parts.hostname in ('books.google.com', 'books.google.nl'):
        query.append(('zoom', '1'))
    return urllib.parse.urlunsplit(('https', parts.netloc, parts.path,
                                   urllib.parse.urlencode(query), ''))


def aliases(isbn='', volume_id='', thumbnail=''):
    result = []
    isbn = str(isbn or '').strip()
    if re.fullmatch(r'\d{13}', isbn):
        result.append('isbn:' + isbn)
    if volume_id:
        result.append('vol:' + str(volume_id).strip())
    url = clean_url(thumbnail)
    if url:
        result.append('url:' + url)
    return result


def collect_books(root):
    """Merge identities across detail files and per-episode analysis records."""
    records = []
    for directory in ('books', 'analysis'):
        for path in sorted((root / 'data' / directory).glob('*.json')):
            data = json.loads(path.read_text(encoding='utf-8'))
            records.extend([data] if directory == 'books' else data.get('books', []))

    groups = []
    for book in records:
        isbn = book.get('isbn13', '')
        vid = book.get('volume_id', '')
        thumbs = [book.get('thumbnail_large', ''), book.get('thumbnail', '')]
        keys = set(aliases(isbn, vid))
        urls = set(filter(None, (clean_url(t) for t in thumbs)))
        keys.update('url:' + url for url in urls)
        if not keys:
            continue
        if re.fullmatch(r'\d{13}', str(isbn or '')):
            urls.add(f'https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false')
        if vid:
            urls.add('https://books.google.com/books/content?' + urllib.parse.urlencode(
                {'id': vid, 'printsec': 'frontcover', 'img': '1', 'zoom': '1'}))
        # Join all matching groups (a later record can bridge ISBN and volume ID).
        matches = [g for g in groups if g['aliases'] & keys]
        for group in matches:
            keys.update(group['aliases'])
            urls.update(group['urls'])
            groups.remove(group)
        groups.append({'aliases': keys, 'urls': urls})
    return groups


def download_image(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'OngelooflijkArchief/1.0 (static book cover cache)',
        'Accept': 'image/*',
    })
    with urllib.request.urlopen(request, timeout=12) as response:
        if not response.headers.get('Content-Type', '').lower().startswith('image/'):
            raise ValueError('not an image response')
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError('cover exceeds download limit')
    return payload


def normalize_image(payload):
    """Reject corrupt/tiny placeholders and strip metadata by re-encoding JPEG."""
    with Image.open(io.BytesIO(payload)) as original:
        original.verify()
    with Image.open(io.BytesIO(payload)) as original:
        if original.width < 40 or original.height < 60:
            raise ValueError('cover is a tiny placeholder')
        pixels = original.convert('L').resize((16, 16)).tobytes()
        mean = sum(pixels) / len(pixels)
        signature = sum(1 << i for i, value in enumerate(pixels) if value > mean)
        if (signature ^ _GOOGLE_PLACEHOLDER_HASH).bit_count() <= 3:
            raise ValueError('Google Books image-not-available placeholder')
        image = ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((640, 960))
        output = io.BytesIO()
        image.save(output, 'JPEG', quality=85, optimize=True)
        return output.getvalue()


def prepare_covers(root=ROOT, output=None, offline=False, retry_missing=False):
    cache = root / 'data' / 'book_covers'
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / 'index.json'
    try:
        previous = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        previous = {}
    now = time.time()
    groups = collect_books(root)

    def process(group):
        keys = sorted(group['aliases'])
        old = [previous[k] for k in keys if k in previous]
        for entry in old:
            filename = entry.get('file', '')
            # The manifest must never select a path outside this cache.
            if filename and pathlib.Path(filename).name == filename:
                path = cache / filename
                if path.is_file():
                    try:
                        normalize_image(path.read_bytes())
                        return keys, entry, 'cached'
                    except Exception:
                        pass
        if offline:
            return keys, {}, 'unavailable'
        if not retry_missing and any(now - e.get('failed_at', 0) < RETRY_SECONDS for e in old):
            return keys, {'failed_at': max(e.get('failed_at', 0) for e in old)}, 'unavailable'
        # Prefer Open Library; Google requests happen only on the build machine.
        urls = sorted(group['urls'], key=lambda u: (
            'openlibrary.org' not in u, 'url:' + u not in group['aliases'], u))
        for url in urls:
            try:
                payload = normalize_image(download_image(url))
                filename = hashlib.sha256(keys[0].encode()).hexdigest()[:24] + '.jpg'
                path = cache / filename
                temporary = path.with_suffix('.tmp')
                temporary.write_bytes(payload)
                temporary.replace(path)
                return keys, {'file': filename, 'source_url': url}, 'downloaded'
            except Exception:
                continue
        return keys, {'failed_at': now}, 'unavailable'

    manifest, counts = {}, {'cached': 0, 'downloaded': 0, 'unavailable': 0}
    with ThreadPoolExecutor(max_workers=4) as executor:
        for i, (keys, entry, status) in enumerate(executor.map(process, groups), 1):
            counts[status] += 1
            for key in keys:
                manifest[key] = entry
            if i % 25 == 0:
                print(f'  Covers processed: {i}/{len(groups)} '
                      f'({counts["downloaded"]} downloaded)', flush=True)
    temporary = manifest_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(manifest_path)

    cover_urls = {}
    if output is not None:
        destination = output / 'data' / 'book_covers'
        destination.mkdir(parents=True, exist_ok=True)
        for filename in {e['file'] for e in manifest.values() if e.get('file')}:
            shutil.copy2(cache / filename, destination / filename)
        cover_urls = {key: '/data/book_covers/' + entry['file']
                      for key, entry in manifest.items() if entry.get('file')}
    print('  Book covers: ' + ', '.join(f'{v} {k}' for k, v in counts.items()), flush=True)
    return cover_urls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--retry-missing', action='store_true')
    args = parser.parse_args()
    prepare_covers(offline=args.offline, retry_missing=args.retry_missing)


if __name__ == '__main__':
    main()
