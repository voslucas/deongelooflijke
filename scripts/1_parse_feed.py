"""Parse the NPO podcast RSS feed and write per-episode feed snapshots.

Usage:
    python scripts/1_parse_feed.py [feed.xml]

Default feed path: data/raw/feed.xml
Outputs:
    data/intermediate/raw.json        (all episodes, legacy format for scripts 2–3)
    data/feed/{n}.json                (per-episode feed snapshot, for analysis pipeline)
"""
import re, json, html, sys, datetime
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_INTERMEDIATE = ROOT / 'data' / 'intermediate'
OUT_FEED = ROOT / 'data' / 'feed'

ns = {'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd'}

# Markers that indicate the start of boilerplate to strip from the description
MARKS = [
    'We gaan weer live', '🔎', '📜', '📱', '📺', '🏛',
    'Relevante afleveringen', '🎧', 'Volg De Ongelooflijke', 'Volg ons',
]


def parse_feed(feed_path):
    t = ET.parse(feed_path)
    ch = t.getroot().find('channel')
    eps = []
    for it in ch.findall('item'):
        g = lambda s: (it.findtext(s, '', ns) or '').strip()
        raw = g('description') or g('itunes:summary')
        txt = html.unescape(re.sub(r'<[^>]+>', ' ', raw))
        txt = re.sub(r'[ \t\r\f\v]+', ' ', txt)
        cut = len(txt)
        for m in MARKS:
            i = txt.find(m)
            if 0 <= i < cut:
                cut = i
        rel = sorted(set(int(x) for x in re.findall(r'🎧\s*#(\d+)', txt)))
        body = re.sub(r'\s*\(https?:[^)]+\)', '', txt[:cut]).strip()
        body = re.sub(r'\s*\n\s*', '\n', body)
        d = parsedate_to_datetime(g('pubDate'))
        dur = g('itunes:duration')
        p = [int(x) for x in dur.split(':')] if dur else [0]
        secs = sum(v * 60 ** i for i, v in enumerate(reversed(p)))
        enc = it.find('enclosure')
        url = enc.get('url') if enc is not None else ''
        m = re.search(r'/file/de-ongelooflijke-podcast/(\d+)/([^?.]+)', url)
        n = g('itunes:episode')
        title = g('title')
        tn = re.match(r'#\s*(\d+)\s*[-–:]?\s*(.*)', title)
        eps.append(dict(
            n=int(n) if n else (int(tn.group(1)) if tn else None),
            title=title,
            t=tn.group(2) if tn else title,
            date=d.date().isoformat(),
            secs=secs,
            desc=body,
            rel=rel,
            npo=m.group(1) if m else '',
            slug=m.group(2) if m else '',
            mp3=url.split('?')[0],
        ))
    return eps


def main():
    feed_path = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / 'data' / 'raw' / 'feed.xml')
    print(f'Parsing {feed_path} …')
    eps = parse_feed(feed_path)
    print(f'  {len(eps)} episodes parsed ({sum(1 for e in eps if e["n"] is None)} without number)')

    # Legacy output for scripts 2–3
    OUT_INTERMEDIATE.mkdir(parents=True, exist_ok=True)
    (OUT_INTERMEDIATE / 'raw.json').write_text(
        json.dumps(eps, ensure_ascii=False, indent=0),
        encoding='utf-8',
    )
    print(f'  → data/intermediate/raw.json')

    # Per-episode feed snapshot
    OUT_FEED.mkdir(parents=True, exist_ok=True)
    fetched = datetime.date.today().isoformat()
    written = 0
    for e in eps:
        key = str(e['n']) if e['n'] is not None else 'x' + e['npo']
        snap = {**e, 'fetched': fetched}
        (OUT_FEED / f'{key}.json').write_text(
            json.dumps(snap, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        written += 1
    print(f'  → data/feed/ ({written} files)')


if __name__ == '__main__':
    main()
