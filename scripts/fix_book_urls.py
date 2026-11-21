"""One-time fix: clean up book records.

Fixes applied to every data/books/*.json:
1. Replace play.google.com infoLinks with stable books.google.nl URLs.
2. Strip time-limited imgtk= / source= tokens from thumbnail URLs so covers
   don't expire within hours of enrichment.
3. Back-fill the is_ebook field introduced by the updated enrichment script.

Run once:
    python scripts/fix_book_urls.py

Pass --dry-run to preview without writing.
"""
import argparse, json, pathlib, re

ROOT      = pathlib.Path(__file__).resolve().parent.parent
DIR_BOOKS = ROOT / 'data' / 'books'


def _stable_thumbnail(url: str) -> str:
    """Strip imgtk/source tokens and zoom so the URL is permanent."""
    if not url:
        return url
    url = re.sub(r'&?imgtk=[^&]+', '', url)
    url = re.sub(r'&?source=[^&]+', '', url)
    url = re.sub(r'&?zoom=\d+', '', url)
    return url.strip('&?')


def fix_file(path: pathlib.Path, dry_run: bool) -> tuple[bool, str]:
    """Return (changed, reason)."""
    try:
        book = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        return False, f'parse error: {exc}'

    changed = False
    url = book.get('google_books_url', '')
    volume_id = book.get('volume_id', '')

    # 1. Fix Play Store URL -> books.google.nl
    if 'play.google.com' in url and volume_id:
        book['google_books_url'] = f'https://books.google.nl/books?id={volume_id}'
        changed = True

    # 2. Strip expired imgtk tokens from thumbnail URLs; ensure zoom=3 on large
    for field in ('thumbnail', 'thumbnail_large'):
        old = book.get(field, '')
        if not old:
            continue
        needs_fix = 'imgtk=' in old or 'source=' in old
        stable = _stable_thumbnail(old) if needs_fix else old
        if field == 'thumbnail_large' and stable and 'zoom=' not in stable:
            stable += ('&' if '?' in stable else '?') + 'zoom=3'
            needs_fix = True
        if needs_fix:
            book[field] = stable
            changed = True

    # 3. Back-fill is_ebook flag
    if 'is_ebook' not in book:
        book['is_ebook'] = 'play.google.com' in url
        changed = True

    if changed and not dry_run:
        path.write_text(json.dumps(book, ensure_ascii=False, indent=2),
                        encoding='utf-8')

    return changed, ''


def main():
    parser = argparse.ArgumentParser(description='Fix play.google.com URLs in book records.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would change without writing')
    args = parser.parse_args()

    files = sorted(DIR_BOOKS.glob('*.json'))
    if not files:
        print('No book files found.')
        return

    fixed = 0
    for f in files:
        changed, err = fix_file(f, args.dry_run)
        if err:
            print(f'  ERROR {f.name}: {err}')
        elif changed:
            fixed += 1
            if args.dry_run:
                book = json.loads(f.read_text(encoding='utf-8'))
                vid = book.get('volume_id', '?')
                print(f'  would fix: {f.name}  -> books.google.nl/books?id={vid}')

    verb = 'Would fix' if args.dry_run else 'Fixed'
    print(f'\n{verb} {fixed}/{len(files)} book files.')
    if not args.dry_run:
        print('Run  python scripts/4_split_data.py && python scripts/5_build_site.py  to rebuild the site.')


if __name__ == '__main__':
    main()
