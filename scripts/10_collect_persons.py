"""Collect unique mentioned persons from analysis files and write enriched detail JSON.

For each unique person mentioned across analysis files, this script:
1. Reads all data/analysis/*.json files
2. Collects unique persons by slug(name) as key
3. Picks the best available Wikipedia data (prefers entries with wiki_pageid, nl > en)
4. Collects all unique notes about the person
5. Writes data/persons_mentioned/{slug}.json

Outputs:
  data/persons_mentioned/{slug}.json — enriched person detail record

Usage:
    python scripts/10_collect_persons.py
"""
import json, pathlib, re, unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
ANALYSIS_DIR = ROOT / 'data' / 'analysis'
OUT_DIR = ROOT / 'data' / 'persons_mentioned'

_ACCENT_RE = re.compile(r'[̀-ͯ]')


def norm(s: str) -> str:
    return _ACCENT_RE.sub('', unicodedata.normalize('NFD', s.lower()))


def slug(s: str) -> str:
    n = norm(s)
    return re.sub(r'[^a-z0-9]+', '-', n).strip('-')


def _lang_rank(lang: str) -> int:
    if lang == 'nl':
        return 0
    if lang == 'en':
        return 1
    return 2


def main():
    if not ANALYSIS_DIR.exists():
        print('No analysis directory found.')
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # by_slug: slug → {name, notes: set, wiki candidates: list of dicts}
    by_slug: dict[str, dict] = {}

    files = sorted(ANALYSIS_DIR.glob('*.json'), key=lambda f: int(f.stem) if f.stem.isdigit() else 0)
    for f in files:
        try:
            an = json.loads(f.read_text(encoding='utf-8'))
        except Exception as exc:
            print(f'  Warning: could not read {f.name}: {exc}')
            continue

        for p in an.get('people', []):
            if not isinstance(p, dict):
                continue
            name = (p.get('name') or '').strip()
            if not name:
                continue
            key = slug(name)
            if not key:
                continue

            if key not in by_slug:
                by_slug[key] = {'name': name, 'notes': set(), 'wiki_candidates': []}

            entry = by_slug[key]

            note = (p.get('note') or '').strip()
            if note:
                entry['notes'].add(note)

            # Collect wiki candidate if data is present
            if p.get('wiki_checked') and p.get('wiki_pageid'):
                entry['wiki_candidates'].append({
                    'wiki_pageid': p['wiki_pageid'],
                    'wiki_lang': p.get('wiki_lang', 'en'),
                    'wiki_url': p.get('wiki_url', ''),
                    'wiki_image': p.get('wiki_image', ''),
                })

    n_written = 0
    for key, entry in by_slug.items():
        # Pick best wiki data: prefer nl over en, then any with image
        candidates = entry['wiki_candidates']
        best = None
        if candidates:
            # Sort: nl first, then en, then others; within same lang prefer those with image
            candidates.sort(key=lambda c: (_lang_rank(c.get('wiki_lang', '')), 0 if c.get('wiki_image') else 1))
            best = candidates[0]

        record: dict = {
            'slug': key,
            'name': entry['name'],
        }
        if best:
            if best.get('wiki_url'):
                record['wiki_url'] = best['wiki_url']
            if best.get('wiki_image'):
                record['wiki_image'] = best['wiki_image']
            if best.get('wiki_lang'):
                record['wiki_lang'] = best['wiki_lang']
            if best.get('wiki_pageid'):
                record['wiki_pageid'] = best['wiki_pageid']

        notes = sorted(entry['notes'])
        if notes:
            record['notes'] = notes

        path = OUT_DIR / f'{key}.json'
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        n_written += 1

    print(f'data/persons_mentioned/: {n_written} person detail files written')


if __name__ == '__main__':
    main()
