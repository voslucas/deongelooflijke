"""Extract social-media links from the RSS feed and write per-person JSON files.

Usage:
    python scripts/6_extract_person_socials.py [feed.xml]

Default feed path: data/raw/feed.xml
Outputs: data/persons/{slug}.json  (additive — never overwrites existing entries)

The RSS boilerplate section of every episode contains David Boogerd's and
Stefan Paas's social links. This script mines those automatically.  Guest-
specific links appear in only ~5 of 329 episodes (mostly Instagram posts, not
profile links), so automated extraction reliably covers the hosts only.
Guests should be added manually to their data/persons/{slug}.json file.
"""
import html, json, pathlib, re, sys, unicodedata
from xml.etree import ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
PERSONS_DIR = ROOT / 'data' / 'persons'

# Same MARKS list as 1_parse_feed.py — these mark the start of the boilerplate
MARKS = [
    'We gaan weer live', '🔎', '📜', '📱', '📺', '🏛',
    'Relevante afleveringen', '🎧', 'Volg De Ongelooflijke', 'Volg ons',
]

# Maps first names found in "Volg <FirstName>" lines to canonical full names
NAME_MAP = {
    'David': 'David Boogerd',
    'Stefan': 'Stefan Paas',
}

PATTERNS = {
    'linkedin': re.compile(r'https?://[^\s)]*linkedin\.com/in/[^\s)]+'),
    'bluesky':  re.compile(r'https?://[^\s)]*bsky\.app/profile/[^\s)]+'),
    'twitter':  re.compile(r'https?://[^\s)]*(?:twitter|x)\.com/(?!intent)[^\s)]+'),
}

# Strips trailing punctuation that gets swept in by the greedy patterns
_TRAIL = re.compile(r'[.,;:!?)\]>]+$')


def slug(s: str) -> str:
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def raw_text(item, ns: dict) -> str:
    raw = item.findtext('description', '', ns) or ''
    txt = html.unescape(re.sub(r'<[^>]+>', ' ', raw))
    return re.sub(r'[ \t\r\f\v]+', ' ', txt)


def boilerplate(txt: str) -> str:
    cut = len(txt)
    for m in MARKS:
        i = txt.find(m)
        if 0 <= i < cut:
            cut = i
    return txt[cut:]


def extract_socials_from_text(text: str) -> dict:
    socials = {}
    for platform, pat in PATTERNS.items():
        m = pat.search(text)
        if m:
            url = _TRAIL.sub('', m.group(0))
            socials[platform] = url
    return socials


def extract_persons_from_boilerplate(boiler: str) -> dict:
    """Return {slug: {name, socials}} by scoping each 'Volg <Name>' block.

    Each block runs from the matching 'Volg <Name>' token up to the next 📱
    marker (another person's block) or end of string, so URLs from adjacent
    blocks cannot bleed across persons.
    """
    result = {}
    for first_name, full_name in NAME_MAP.items():
        k = slug(full_name)
        pat = re.compile(rf'(?:📱\s*)?Volg\s+{re.escape(first_name)}\b')
        m = pat.search(boiler)
        if not m:
            continue
        start = m.start()
        # End at the next 📱 character after the current block starts
        next_block = re.search(r'📱', boiler[start + 1:])
        end = start + 1 + next_block.start() if next_block else len(boiler)
        segment = boiler[start:end]
        socials = extract_socials_from_text(segment)
        if socials:
            result[k] = {'name': full_name, 'socials': socials}
    return result


def write_person_file(path: pathlib.Path, new_socials: dict) -> str:
    """Write or update a person JSON file.  Returns 'created'/'updated'/'unchanged'."""
    if path.exists():
        existing = json.loads(path.read_text(encoding='utf-8'))
        changed = False
        for platform, url in new_socials.items():
            if platform not in existing.setdefault('socials', {}):
                existing['socials'][platform] = url
                changed = True
        if changed:
            path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            return 'updated'
        return 'unchanged'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({'socials': new_socials}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return 'created'


def main() -> None:
    feed_path = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / 'data' / 'raw' / 'feed.xml')
    print(f'Parsing {feed_path} …')

    ns = {'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd'}
    tree = ET.parse(feed_path)
    items = tree.getroot().find('channel').findall('item')

    # Accumulate one merged socials dict per person (first URL wins per platform)
    found: dict[str, dict] = {}  # slug → {name, socials}

    # Collect per-person per-platform URL → count (to filter feed errors)
    counts: dict[str, dict[str, dict[str, int]]] = {}  # slug → platform → url → count
    for item in items:
        txt = raw_text(item, ns)
        boiler = boilerplate(txt)
        for k, data in extract_persons_from_boilerplate(boiler).items():
            pc = counts.setdefault(k, {})
            for platform, url in data['socials'].items():
                pc.setdefault(platform, {})[url] = pc.setdefault(platform, {}).get(url, 0) + 1
            found.setdefault(k, {'name': data['name'], 'socials': {}})

    # Keep only URLs that appear in ≥2 episodes (guards against feed typos)
    MIN_COUNT = 2
    for k, pc in counts.items():
        for platform, url_counts in pc.items():
            best_url = max(url_counts, key=lambda u: url_counts[u])
            if url_counts[best_url] >= MIN_COUNT:
                found[k]['socials'][platform] = best_url

    if not found:
        print('No social links found in feed boilerplate.')
        return

    created = updated = unchanged = 0
    for k, entry in sorted(found.items()):
        path = PERSONS_DIR / f'{k}.json'
        result = write_person_file(path, entry['socials'])
        print(f'  {result:9s}  {path.name}  {list(entry["socials"].keys())}')
        if result == 'created':
            created += 1
        elif result == 'updated':
            updated += 1
        else:
            unchanged += 1

    print(f'\nDone: {created} created, {updated} updated, {unchanged} unchanged.')
    print(f'Person files are in {PERSONS_DIR}')
    print('To add a guest manually, create data/persons/{slug}.json with the same schema.')


if __name__ == '__main__':
    main()
