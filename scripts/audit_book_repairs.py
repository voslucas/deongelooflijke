"""Audit repaired book records and write a consolidated remaining-work report.

--apply removes unverified work-level covers from Dutch recommendations and
normalizes ISBN-10 to the selected ISBN-13. No network requests are made.
"""
import argparse
from collections import Counter
import json
import pathlib
import re

from PIL import Image

from book_covers import aliases
from repair_books_openlibrary import (ROOT, collect_targets, isbn10_from_isbn13,
                                     language_preference, valid_isbn13, write_json)
from repair_books_bibliotheek import valid_cover
from utils import slug


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    manifest_path = ROOT / 'data/book_covers/index.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    with Image.open(ROOT / 'data/book_covers/a0fb7fe96c499d4e7c090478.jpg') as image:
        reference = image.convert('RGB').resize((32, 40))
    records = []
    rejected = []
    invalid = []
    for path in sorted((ROOT / 'data/books').glob('*.json')):
        book = json.loads(path.read_text(encoding='utf-8'))
        changed = False
        if book.get('isbn13') and not valid_isbn13(book['isbn13']):
            invalid.append({'key': book['key'], 'title': book['title'], 'isbn13': book['isbn13']})
        if valid_isbn13(book.get('isbn13')):
            paired = isbn10_from_isbn13(book['isbn13'])
            if book.get('isbn10', '') != paired:
                book['isbn10'] = paired
                changed = True
        if book.get('openlibrary_match') == 'work-only' and 'covers.openlibrary.org' in book.get('thumbnail', '') and language_preference(
                book.get('recommended_title') or book['title'], book) == 'dut':
            old = book['thumbnail']
            entries = [manifest[a] for a in aliases(book.get('isbn13'), book.get('volume_id'), old) if a in manifest]
            files = {e.get('file') for e in entries if e.get('source_url') == old}
            manifest = {a: e for a, e in manifest.items() if e.get('file') not in files}
            book['unverified_thumbnail'] = old
            book['thumbnail'] = book['thumbnail_large'] = ''
            book['cover_review_reason'] = 'Work-level image was not verified as a Dutch edition; no Dutch replacement was found.'
            rejected.append(book['key'])
            changed = True
        if args.apply and changed:
            write_json(path, book)
        records.append(book)
    if args.apply:
        write_json(manifest_path, manifest)
        rejected_books = [b for b in records if b.get('cover_review_reason') and b.get('unverified_thumbnail')]
        for path in (ROOT / 'data/analysis').glob('*.json'):
            analysis = json.loads(path.read_text(encoding='utf-8'))
            changed = False
            for mention in analysis.get('books', []):
                key = mention.get('isbn13') or ('vol-' + mention['volume_id'] if mention.get('volume_id') else
                                               slug(mention.get('canonical_title') or mention.get('title', '')))
                for book in rejected_books:
                    identities = {book['key'], book.get('isbn13'), 'vol-' + book['volume_id'] if book.get('volume_id') else ''}
                    if key in identities and mention.get('thumbnail') == book['unverified_thumbnail']:
                        mention['thumbnail'] = ''
                        changed = True
            if changed:
                write_json(path, analysis)
    remaining = []
    gaps = Counter()
    for key, path, record, missing in collect_targets(manifest, reference):
        gaps.update(missing)
        remaining.append({'key': key, 'title': record['title'], 'author': record.get('author', ''),
                          'missing': missing, 'has_detail_record': path.exists()})
    # Inspect coverage of public book routes, including original ISBN/volume/slug
    # aliases. Stage 4's aggregate identities are unchanged by the repair scripts.
    by_key = {}
    for book in records:
        for key in (book['key'], book.get('isbn13'), 'vol-' + book['volume_id'] if book.get('volume_id') else ''):
            if key:
                by_key[key] = book
    aggregates_path = ROOT / 'site/dist/data/books.json'
    coverage = Counter()
    if aggregates_path.exists():
        for aggregate in json.loads(aggregates_path.read_text(encoding='utf-8')):
            key = aggregate.get('book_key') or aggregate.get('isbn13') or slug(aggregate.get('n', ''))
            book = by_key.get(key, {})
            coverage['book_pages'] += 1
            coverage['with_detail_record'] += bool(book)
            isbn = book.get('isbn13') or (key if re.fullmatch(r'\d{13}', key) else '')
            volume = book.get('volume_id') or (key[4:] if key.startswith('vol-') else '')
            thumb = book.get('thumbnail_large') or book.get('thumbnail') or aggregate.get('bk_thumb', '')
            has_cover = any(manifest.get(a, {}).get('file') and valid_cover(
                ROOT / 'data/book_covers' / manifest[a]['file'], reference) for a in aliases(isbn, volume, thumb))
            coverage['with_local_cover'] += bool(has_cover)
    report_names = ['book_repair_report.json', 'book_repair_bibliotheek_report.json',
                    'book_repair_edition_report.json', 'book_repair_alias_report.json']
    provenance = {}
    for name in report_names:
        path = ROOT / 'data' / name
        if path.exists():
            report = json.loads(path.read_text(encoding='utf-8'))
            applied = [v for v in report.values() if v.get('applied')]
            provenance[name] = {'outcomes': dict(Counter(v['status'] for v in applied)),
                                'covers_downloaded': sum(v.get('cover') == 'downloaded' for v in applied)}
    summary = {'detail_records': len(records), 'public_coverage': dict(coverage),
               'remaining_records': len(remaining), 'remaining_field_gaps': dict(gaps),
               'remaining_without_detail_record': sum(not r['has_detail_record'] for r in remaining),
               'unverified_dutch_covers_removed': sorted(set(rejected + [b['key'] for b in records if b.get('cover_review_reason')])),
               'invalid_isbn13': invalid,
               'repair_reports': provenance, 'remaining': remaining}
    write_json(ROOT / 'data/book_repair_summary.json', summary)
    print(json.dumps({k: v for k, v in summary.items() if k != 'remaining'}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
