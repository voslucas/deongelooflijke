"""Build the app shell: inline a lightweight episode index + logos -> site/dist/index.html.

The inline index contains only the fields needed for search and listing:
  n t d s g p th f kw xs
Heavy fields (x r id sl q mp3) are absent; they are fetched on demand from
site/dist/data/episodes/{key}.json when the user opens an episode detail view.

Also inlines a compact verse table (bvdata) from data/bible/*.json covering all
referenced Bible passages so the popup can show NBV21 text without runtime fetches.
"""
import base64, json, pathlib, re, shutil
from utils import truncate_xs

ROOT = pathlib.Path(__file__).resolve().parent.parent
EP_DIR = ROOT / 'site' / 'dist' / 'data' / 'episodes'
BIBLE_DIR = ROOT / 'data' / 'bible'
TRANSCRIPTS_DIR = ROOT / 'data' / 'transcripts'
ANALYSIS_DIR = ROOT / 'data' / 'analysis'

# Fields that go into the lightweight inline index (no heavy detail fields)
LIGHT_FIELDS = {'n', 't', 'd', 's', 'g', 'p', 'th', 'f', 'kw', 'xs', 'q', 'r'}

# Fields to strip from the per-episode files when building the inline index
HEAVY_FIELDS = {'x', 'r', 'id', 'sl', 'q', 'mp3'}

# Dutch book name → OSIS 3-letter code
DUTCH_TO_OSIS = {
    'genesis': 'GEN', 'exodus': 'EXO', 'leviticus': 'LEV', 'numeri': 'NUM',
    'deuteronomium': 'DEU', 'jozua': 'JOS', 'rechters': 'JDG', 'ruth': 'RUT',
    '1 samuel': '1SA', '2 samuel': '2SA', '1 koningen': '1KI', '2 koningen': '2KI',
    '1 kronieken': '1CH', '2 kronieken': '2CH', 'ezra': 'EZR', 'nehemia': 'NEH',
    'esther': 'EST', 'job': 'JOB', 'psalm': 'PSA', 'psalmen': 'PSA',
    'spreuken': 'PRO', 'prediker': 'ECC', 'hooglied': 'SNG', 'jesaja': 'ISA',
    'jeremia': 'JER', 'klaagliederen': 'LAM', 'ezechiël': 'EZK', 'ezechiel': 'EZK',
    'daniël': 'DAN', 'daniel': 'DAN', 'hosea': 'HOS', 'joël': 'JOL', 'joel': 'JOL',
    'amos': 'AMO', 'obadja': 'OBA', 'jona': 'JON', 'micha': 'MIC', 'nahum': 'NAH',
    'habakuk': 'HAB', 'sefanja': 'ZEP', 'haggai': 'HAG', 'zacharia': 'ZEC',
    'maleachi': 'MAL', 'matteüs': 'MAT', 'matteus': 'MAT', 'mattheus': 'MAT',
    'marcus': 'MRK', 'lucas': 'LUK', 'johannes': 'JHN', 'handelingen': 'ACT',
    'romeinen': 'ROM', '1 korintiërs': '1CO', '1 korinthiers': '1CO',
    '2 korintiërs': '2CO', '2 korinthiers': '2CO', 'galaten': 'GAL',
    'efeziërs': 'EPH', 'efeziers': 'EPH', 'filippenzen': 'PHP', 'kolossenzen': 'COL',
    '1 tessalonicenzen': '1TH', '2 tessalonicenzen': '2TH',
    '1 timoteüs': '1TI', '1 timoteus': '1TI', '2 timoteüs': '2TI', '2 timoteus': '2TI',
    'titus': 'TIT', 'filemon': 'PHM', 'hebreeën': 'HEB', 'hebreeen': 'HEB',
    'jakobus': 'JAS', '1 petrus': '1PE', '2 petrus': '2PE',
    '1 johannes': '1JO', '2 johannes': '2JO', '3 johannes': '3JO',
    'judas': 'JUD', 'openbaring': 'REV',
}

# Synthetic refs in the template BIBLE constant (book chapter, no verse)
_TEMPLATE_BIBLE = [
    'Genesis 1', 'Genesis 22', 'Exodus 3', 'Psalm 23', 'Psalm 139',
    'Prediker 3', 'Jesaja 53', 'Matteüs 5', 'Matteüs 25', 'Lucas 15',
    'Johannes 1', 'Johannes 3', 'Romeinen 8', '1 Korintiërs 13', 'Openbaring 21',
]

_REF_RE = re.compile(
    r'^(?P<book>(?:\d\s+)?[A-Za-zÀ-ÿÀ-ɏ]+(?:\s+[A-Za-zÀ-ÿÀ-ɏ]+)*)'
    r'\s+(?P<ch>\d+)(?::(?P<v>\d+)(?:-\d+)?)?',
)


def parse_ref(ref: str):
    """Parse Dutch Bible ref → (OSIS_code, chapter, verse) or None."""
    ref = ref.strip()
    ref = re.sub(r'\s*\(.*\)', '', ref).strip()
    ref = re.sub(r'(\d+)-\d+', r'\1', ref)
    m = _REF_RE.match(ref)
    if not m:
        return None
    book_raw = m.group('book').strip().lower()
    ch = int(m.group('ch'))
    v = int(m.group('v')) if m.group('v') else 1
    code = DUTCH_TO_OSIS.get(book_raw)
    if not code:
        return None
    return code, ch, v


def build_bible_data() -> dict:
    """Return compact verse dict keyed by "CODE.CH.V" → [text_v, text_v+1, text_v+2]."""
    if not BIBLE_DIR.exists():
        return {}

    book_cache: dict[str, dict] = {}

    def get_book(code: str) -> dict:
        if code not in book_cache:
            f = BIBLE_DIR / f'{code}.json'
            book_cache[code] = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
        return book_cache[code]

    def verses_for(code: str, ch: int, v: int) -> list[str]:
        ch_data = get_book(code).get(str(ch), {})
        return [ch_data[str(v + i)] for i in range(3) if str(v + i) in ch_data]

    all_refs: set[str] = set(_TEMPLATE_BIBLE)

    if ANALYSIS_DIR.exists():
        for f in ANALYSIS_DIR.glob('*.json'):
            try:
                for b in json.loads(f.read_text(encoding='utf-8')).get('bible_refs', []):
                    if b.get('ref'):
                        all_refs.add(b['ref'])
            except Exception:
                pass

    if TRANSCRIPTS_DIR.exists():
        for f in TRANSCRIPTS_DIR.glob('*.json'):
            try:
                for b in json.loads(f.read_text(encoding='utf-8')).get('bible', []):
                    if b.get('ref'):
                        all_refs.add(b['ref'])
            except Exception:
                pass

    bv: dict[str, list[str]] = {}
    missing: set[str] = set()

    for ref in sorted(all_refs):
        parsed = parse_ref(ref)
        if not parsed:
            continue
        code, ch, v = parsed
        key = f'{code}.{ch}.{v}'
        if key in bv:
            continue
        texts = verses_for(code, ch, v)
        if texts:
            bv[key] = texts
        else:
            missing.add(code)

    if missing:
        print(f'  Note: no bible data for {", ".join(sorted(missing))} '
              f'(run scripts/scrape_nbv21.py first)')
    print(f'  Bible verse data: {len(bv)} entries from {len(all_refs)} refs')
    return bv


def build_lightweight_index():
    """Read all per-episode files from site/dist/data/episodes/ and return
    a lightweight list (only LIGHT_FIELDS) sorted by episode number desc."""
    entries = []
    for f in EP_DIR.glob('*.json'):
        ep = json.loads(f.read_text(encoding='utf-8'))
        # Compute xs from x (truncated description)
        ep['xs'] = truncate_xs(ep.get('x', ''))
        # Keep only light fields
        light = {k: v for k, v in ep.items() if k in LIGHT_FIELDS}
        entries.append(light)
    # Sort: numbered episodes by n desc, unnumbered at end
    entries.sort(key=lambda e: (e['n'] is None, -(e['n'] or 0)))
    return entries


def load_persons_data(root: pathlib.Path) -> dict:
    """Read data/persons/*.json, detect images, return {slug: {socials?, img?}}."""
    persons_dir = root / 'data' / 'persons'
    img_dir = persons_dir / 'images'
    result = {}
    if not persons_dir.exists():
        return result
    for f in sorted(persons_dir.glob('*.json')):
        k = f.stem
        try:
            obj = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        has_img = any(
            (img_dir / f'{k}{ext}').exists()
            for ext in ('.jpg', '.jpeg', '.jfif', '.png', '.webp')
        )
        entry: dict = {}
        if obj.get('socials'):
            entry['socials'] = obj['socials']
        if has_img:
            entry['img'] = True
        if entry:
            result[k] = entry
    return result


def main():
    # Read full episodes.json for bios and built date
    full_data = json.loads((ROOT / 'data' / 'episodes.json').read_text(encoding='utf-8'))

    # Build lightweight index
    index_eps = build_lightweight_index()

    # Assemble the inlined data object (same shape as before, eps is now lightweight)
    inline_data = {
        'eps': index_eps,
        'bios': full_data['bios'],
        'built': full_data['built'],
        'persons': load_persons_data(ROOT),
    }

    # Read template and replace placeholders
    template = (ROOT / 'site' / 'src' / 'index.template.html').read_text(encoding='utf-8')

    b64 = lambda p, m: f"data:{m};base64," + base64.b64encode((ROOT / p).read_bytes()).decode()

    bv = build_bible_data()
    bv_json = json.dumps(bv, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')

    out = (
        template
        .replace('__DATA__', json.dumps(inline_data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
        .replace('__BVDATA__', bv_json)
        .replace('__LOGO__', b64('design-system/assets/logos/logo360.jpg', 'image/jpeg'))
        .replace('__WORDMARK__', b64('design-system/assets/logos/wordmark672.png', 'image/png'))
    )

    dist = ROOT / 'site' / 'dist'
    dist.mkdir(parents=True, exist_ok=True)
    (dist / 'index.html').write_text(out, encoding='utf-8')
    print(f'site/dist/index.html {len(out)} bytes  ({len(index_eps)} episodes in index)')

    # Copy person images to site/dist/data/persons/images/
    img_src = ROOT / 'data' / 'persons' / 'images'
    img_dst = dist / 'data' / 'persons' / 'images'
    if img_src.exists():
        img_dst.mkdir(parents=True, exist_ok=True)
        n_imgs = 0
        for f in img_src.iterdir():
            ext = f.suffix.lower()
            if ext in ('.jpg', '.jpeg', '.jfif', '.png', '.webp'):
                # JFIF is JPEG — rename to .jpg so the site's hard-coded URL resolves
                dst_name = f.stem + '.jpg' if ext == '.jfif' else f.name
                shutil.copy2(f, img_dst / dst_name)
                n_imgs += 1
        if n_imgs:
            print(f'  copied {n_imgs} person image(s) to site/dist/data/persons/images/')

    # Copy word index (produced by scripts/9_build_word_index.py)
    wi_src = ROOT / 'data' / 'word_index.json'
    if wi_src.exists():
        (dist / 'data').mkdir(parents=True, exist_ok=True)
        shutil.copy2(wi_src, dist / 'data' / 'word_index.json')
        size_kb = wi_src.stat().st_size / 1024
        print(f'  copied word_index.json ({size_kb:.0f} KB) to site/dist/data/')

    # Copy transcripts (speaker names are already correct in the source files)
    tx_src = ROOT / 'data' / 'transcripts'
    tx_dst = dist / 'data' / 'transcripts'
    if tx_src.exists():
        tx_dst.mkdir(parents=True, exist_ok=True)
        n_tx = 0
        for f in tx_src.glob('*.json'):
            try:
                tr = json.loads(f.read_text(encoding='utf-8'))
                (tx_dst / f.name).write_text(
                    json.dumps(tr, ensure_ascii=False, separators=(',', ':')),
                    encoding='utf-8',
                )
                n_tx += 1
            except Exception as exc:
                print(f'  Warning: could not process transcript {f.name}: {exc}')
                shutil.copy2(f, tx_dst / f.name)
                n_tx += 1
        if n_tx:
            print(f'  copied {n_tx} transcript(s) to site/dist/data/transcripts/')


if __name__ == '__main__':
    main()
