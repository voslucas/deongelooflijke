"""Build the app shell: inline a lightweight episode index + logos -> site/dist/index.html.

The inline index contains only the fields needed for search and listing:
  n t d s g p sj th f kw xs
Heavy fields (x r id sl q mp3) are absent; they are fetched on demand from
site/dist/data/episodes/{key}.json when the user opens an episode detail view.
"""
import base64, json, pathlib, re, shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
EP_DIR = ROOT / 'site' / 'dist' / 'data' / 'episodes'

# Fields that go into the lightweight inline index (no heavy detail fields)
LIGHT_FIELDS = {'n', 't', 'd', 's', 'g', 'p', 'sj', 'th', 'f', 'kw', 'xs', 'q', 'r'}

# Fields to strip from the per-episode files when building the inline index
HEAVY_FIELDS = {'x', 'r', 'id', 'sl', 'q', 'mp3'}


def truncate_xs(text, max_chars=320):
    """Truncate description at word boundary, ≤320 chars."""
    if not text:
        return ''
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(None, 1)[0]
    return cut if cut else text[:max_chars]


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
    }

    # Read template and replace placeholders
    template = (ROOT / 'site' / 'src' / 'index.template.html').read_text(encoding='utf-8')

    b64 = lambda p, m: f"data:{m};base64," + base64.b64encode((ROOT / p).read_bytes()).decode()

    out = (
        template
        .replace('__DATA__', json.dumps(inline_data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
        .replace('__LOGO__', b64('design-system/assets/logos/logo360.jpg', 'image/jpeg'))
        .replace('__WORDMARK__', b64('design-system/assets/logos/wordmark672.png', 'image/png'))
    )

    dist = ROOT / 'site' / 'dist'
    dist.mkdir(parents=True, exist_ok=True)
    (dist / 'index.html').write_text(out, encoding='utf-8')
    print(f'site/dist/index.html {len(out)} bytes  ({len(index_eps)} episodes in index)')

    # Copy transcripts from data/transcripts/ so the page can fetch them
    tx_src = ROOT / 'data' / 'transcripts'
    tx_dst = dist / 'data' / 'transcripts'
    if tx_src.exists():
        tx_dst.mkdir(parents=True, exist_ok=True)
        for f in tx_src.glob('*.json'):
            shutil.copy2(f, tx_dst / f.name)
        n_tx = len(list(tx_src.glob('*.json')))
        if n_tx:
            print(f'  copied {n_tx} transcript(s) to site/dist/data/transcripts/')


if __name__ == '__main__':
    main()
