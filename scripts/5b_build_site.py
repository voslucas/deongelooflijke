"""
5b_build_site.py — Static multi-page site generator

Generates a fully static site in site/static/ from the same
site/dist/data/ files produced by 4_split_data.py.

Usage:
    python scripts/5b_build_site.py [--output-dir DIR] [--base-url URL] [--clean]

Run after: python scripts/4_split_data.py
"""
import argparse, json, math, pathlib, re, shutil, unicodedata
from collections import defaultdict
from datetime import date as _date
from html import escape as _esc
from book_covers import aliases as cover_aliases, prepare_covers

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST_DATA = ROOT / 'site' / 'dist' / 'data'
DEFAULT_OUT = ROOT / 'site' / 'static'
TEMPLATE = ROOT / 'site' / 'src' / 'index.template.html'

MONTHS_NL = ['januari','februari','maart','april','mei','juni',
              'juli','augustus','september','oktober','november','december']
DAYS_NL = ['zondag','maandag','dinsdag','woensdag','donderdag','vrijdag','zaterdag']

DUTCH_TO_OSIS = {
    'genesis': 'GEN', 'exodus': 'EXO', 'leviticus': 'LEV', 'numeri': 'NUM',
    'deuteronomium': 'DEU', 'jozua': 'JOS', 'rechters': 'JDG', 'ruth': 'RUT',
    '1 samuel': '1SA', '2 samuel': '2SA', '1 koningen': '1KI', '2 koningen': '2KI',
    '1 kronieken': '1CH', '2 kronieken': '2CH', 'ezra': 'EZR', 'nehemia': 'NEH',
    'esther': 'EST', 'job': 'JOB', 'psalm': 'PSA', 'psalmen': 'PSA',
    'spreuken': 'PRO', 'prediker': 'ECC', 'hooglied': 'SNG', 'jesaja': 'ISA',
    'jeremia': 'JER', 'klaagliederen': 'LAM', 'ezechiel': 'EZK',
    'daniel': 'DAN', 'hosea': 'HOS', 'joel': 'JOL',
    'amos': 'AMO', 'obadja': 'OBA', 'jona': 'JON', 'micha': 'MIC', 'nahum': 'NAH',
    'habakuk': 'HAB', 'sefanja': 'ZEP', 'haggai': 'HAG', 'zacharia': 'ZEC',
    'maleachi': 'MAL', 'matteus': 'MAT', 'mattheus': 'MAT',
    'marcus': 'MRK', 'lucas': 'LUK', 'johannes': 'JHN', 'handelingen': 'ACT',
    'romeinen': 'ROM', '1 korinthiers': '1CO', '2 korinthiers': '2CO',
    'galaten': 'GAL', 'efeziers': 'EPH', 'filippenzen': 'PHP', 'kolossenzen': 'COL',
    '1 tessalonicenzen': '1TH', '2 tessalonicenzen': '2TH',
    '1 timoteus': '1TI', '2 timoteus': '2TI',
    'titus': 'TIT', 'filemon': 'PHM', 'hebreeen': 'HEB',
    'jakobus': 'JAS', '1 petrus': '1PE', '2 petrus': '2PE',
    '1 johannes': '1JN', '2 johannes': '2JN', '3 johannes': '3JN',
    'judas': 'JUD', 'openbaring': 'REV',
}

_REF_RE = re.compile(
    r'^(?P<book>(?:\d\s+)?[A-Za-zÀ-ɏ]+(?:\s+[A-Za-zÀ-ɏ]+)*)'
    r'\s+(?P<ch>\d+)(?::(?P<v>\d+)(?:-\d+)?)?')

def parse_ref(ref: str):
    """Parse Dutch Bible ref → (OSIS_code, chapter, verse) or None."""
    ref = ref.strip()
    ref = re.sub(r'\s*\(.*\)', '', ref).strip()
    ref = re.sub(r'(\d+)-\d+', r'\1', ref)
    m = _REF_RE.match(ref)
    if not m:
        return None
    book_raw = m.group('book').strip().lower()
    import unicodedata as _ud
    book_norm = ''.join(c for c in _ud.normalize('NFD', book_raw) if _ud.category(c) != 'Mn')
    ch = int(m.group('ch'))
    v = int(m.group('v')) if m.group('v') else 1
    code = DUTCH_TO_OSIS.get(book_raw) or DUTCH_TO_OSIS.get(book_norm)
    if not code:
        return None
    return code, ch, v

# Social icon SVG literals (same as template)
IC_LINKEDIN = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="1.5" y="1.5" width="13" height="13" rx="2.5"/><line x1="5" y1="7" x2="5" y2="12"/><circle cx="5" cy="4.5" r=".75" fill="currentColor" stroke="none"/><path d="M8 12V9.5a2 2 0 0 1 4 0V12M8 7v5"/></svg>'
IC_TWITTER  = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><path d="M2.5 2.5l11 11M13.5 2.5l-11 11"/></svg>'
IC_BLUESKY  = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 10C6 8.5 2.5 6 1.5 7.5c-.5.8-.3 2 .5 2.5C3 10.5 5 10 6 10.5 5 11 3 12.5 3.5 14c.4 1 2 1 3-.5L8 11"/><path d="M8 10c2-1.5 5.5-4 6.5-2.5.5.8.3 2-.5 2.5C13 10.5 11 10 10 10.5c1 .5 3 2 2.5 3.5-.4 1-2 1-3-.5L8 11"/></svg>'
IC_WEBSITE  = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="6.5"/><path d="M8 1.5C6.2 3.5 6.2 12.5 8 14.5"/><path d="M1.5 8h13"/><path d="M2.2 5.5c1.6.5 3.7.8 5.8.8s4.2-.3 5.8-.8M2.2 10.5c1.6-.5 3.7-.8 5.8-.8s4.2.3 5.8.8" opacity=".6"/></svg>'
SOCIAL_ICONS = {'linkedin':(IC_LINKEDIN,'LinkedIn'),'twitter':(IC_TWITTER,'Twitter / X'),
                'bluesky':(IC_BLUESKY,'Bluesky'),'website':(IC_WEBSITE,'Website')}

# Module-level mutable state (set once during main())
_BUILT_DATE = ''
_BASE_URL = 'https://www.deongelooflijkearchief.nl'
_COVER_URLS = {}
_BVDATA: dict = {}  # Bible verse data: "CODE.ch.v" → [verse_text, ...]

# ============================================================
# SECTION 1: UTILITIES
# ============================================================

def esc(s):
    return _esc(str(s)) if s is not None else ''

def slug(s):
    s = unicodedata.normalize('NFD', str(s).lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')

def norm(s):
    s = unicodedata.normalize('NFD', str(s).lower())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')

def ep_key(e):
    return str(e['n']) if e.get('n') is not None else 'x' + e['id']

def fmt_dur(seconds):
    if not seconds:
        return '—'
    h = int(seconds // 3600)
    m = round((seconds % 3600) / 60)
    if h:
        return f'{h} u {m:02d} min'
    return f'{m} min'

def fmt_date(d):
    if not d:
        return ''
    parts = str(d).split('-')
    if len(parts) != 3:
        return str(d)
    y, mo, dd = parts
    return f'{int(dd)} {MONTHS_NL[int(mo)-1]} {y}'

def fmt_hours(seconds):
    h = seconds / 3600
    return f'{h:.0f}' if h >= 100 else f'{h:.1f}'.replace('.', ',')

def ts_fmt(secs):
    s = max(0, round(secs))
    h, rem = divmod(s, 3600)
    m, x = divmod(rem, 60)
    if h:
        return f'{h}:{m:02d}:{x:02d}'
    return f'{m}:{x:02d}'

def initials(name):
    parts = [w for w in str(name).split() if w and w[0].isupper()]
    ini = ''.join(w[0] for w in parts[:2])
    return ini or (name[0] if name else '?')

def strip_html(s):
    return re.sub(r'<[^>]+>', '', str(s or ''))

def npo_url(e):
    if e.get('id') and e.get('sl'):
        n_part = f"{e['n']}-" if e.get('n') is not None else ''
        return f"https://www.nporadio1.nl/podcasts/de-ongelooflijke-podcast/{e['id']}/{n_part}{e['sl']}"
    return ''

# ============================================================
# SECTION 2: DATA LOADING
# ============================================================

class SiteData:
    __slots__ = ['index','episodes','people_dict','people_list','books_list','speakers',
                 'bios','persons_data','built','guests','themes','theme_eps',
                 'ep_by_key','ep_by_num','all_eps','reg_eps','years',
                 'persons_detail','books_detail']

def load_data(dist_data: pathlib.Path) -> 'SiteData':
    d = SiteData()
    idx_path = dist_data / 'index.json'
    d.index = json.loads(idx_path.read_text(encoding='utf-8')) if idx_path.exists() else []

    d.episodes = {}
    ep_dir = dist_data / 'episodes'
    if ep_dir.exists():
        for f in ep_dir.glob('*.json'):
            try:
                ep = json.loads(f.read_text(encoding='utf-8'))
                d.episodes[ep_key(ep)] = ep
            except Exception as exc:
                print(f'  Warning: {f.name}: {exc}')
    print(f'  Loaded {len(d.episodes)} episodes')

    def load_json(path, default=None):
        try:
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
        except Exception:
            return default

    # people.json is a LIST of aggregates; books.json is also a list
    ppl_raw = load_json(dist_data / 'people.json', [])
    if isinstance(ppl_raw, list):
        # Build lookup by slug for detail pages; keep raw list for overview
        d.people_list = ppl_raw
        for item in d.people_list:
            if not item.get('slug'):
                item['slug'] = slug(item.get('n', ''))
        d.people_dict = {item['slug']: item for item in d.people_list}
    else:
        # Legacy: dict keyed by slug
        d.people_dict = ppl_raw
        d.people_list = list(ppl_raw.values())
    d.books_list  = load_json(dist_data / 'books.json', [])
    d.speakers    = load_json(dist_data / 'speakers.json', {})

    master_path = ROOT / 'data' / 'episodes.json'
    if master_path.exists():
        master = json.loads(master_path.read_text(encoding='utf-8'))
        d.bios  = master.get('bios', {})
        d.built = master.get('built', str(_date.today()))
    else:
        d.bios, d.built = {}, str(_date.today())

    # persons social/image data
    d.persons_data = {}
    persons_dir = ROOT / 'data' / 'persons'
    img_dir = persons_dir / 'images'
    if persons_dir.exists():
        for f in sorted(persons_dir.glob('*.json')):
            k = f.stem
            try:
                obj = json.loads(f.read_text(encoding='utf-8'))
                has_img = any((img_dir / f'{k}{ext}').exists()
                              for ext in ('.jpg','.jpeg','.jfif','.png','.webp'))
                entry = {}
                if obj.get('socials'): entry['socials'] = obj['socials']
                if has_img: entry['img'] = True
                if obj.get('bio'): entry['bio'] = obj['bio']
                if entry: d.persons_data[k] = entry
            except Exception:
                pass

    # Build ordered episode list
    ordered_keys = d.index if d.index else sorted(
        d.episodes.keys(), key=lambda k: -(d.episodes[k].get('n') or 0))
    d.all_eps  = [d.episodes[k] for k in ordered_keys if k in d.episodes]
    d.reg_eps  = [e for e in d.all_eps if e.get('f') not in ('Trailer','Spin-off')]
    d.ep_by_key = d.episodes
    d.ep_by_num = {e['n']: e for e in d.all_eps if e.get('n') is not None}
    d.years = sorted(set(int(e['d'][:4]) for e in d.all_eps if e.get('d')))

    # Build guests dict
    d.guests = {}
    def add_guest(name, ep, role):
        k = slug(name)
        if k not in d.guests:
            d.guests[k] = {'name': name, 'k': k, 'role': role, 'eps': [], 'secs': 0}
        d.guests[k]['eps'].append(ep)
        d.guests[k]['secs'] += ep.get('s', 0)

    for ep in d.all_eps:
        for g in ep.get('g', []):
            add_guest(g, ep, 'Gast')
        if ep.get('p') and ep.get('f') != 'Trailer':
            add_guest('Stefan Paas', ep, 'Vaste gast')
        if ep.get('f') not in ('Trailer', 'Spin-off'):
            add_guest('David Boogerd', ep, 'Presentator')

    for g in d.guests.values():
        g['eps'].sort(key=lambda e: e.get('d',''))
        pd = d.persons_data.get(g['k'], {})
        g['socials'] = pd.get('socials')
        g['img'] = pd.get('img', False)
        g['bio'] = pd.get('bio') or d.bios.get(g['name'],'')

    for special, role in [('stefan-paas','Vaste gast'),('david-boogerd','Presentator')]:
        if special in d.guests:
            d.guests[special]['role'] = role

    # Build themes
    theme_counts = defaultdict(int)
    d.theme_eps = defaultdict(list)
    for ep in d.all_eps:
        for t in ep.get('th', []):
            theme_counts[t] += 1
            d.theme_eps[t].append(ep)
    d.themes = sorted(theme_counts, key=lambda t: -theme_counts[t])

    # persons_detail (mentioned persons)
    d.persons_detail = {}
    pm_dir = dist_data / 'persons_mentioned'
    if pm_dir.exists():
        for f in pm_dir.glob('*.json'):
            try:
                d.persons_detail[f.stem] = json.loads(f.read_text(encoding='utf-8'))
            except Exception:
                pass

    # books_detail
    d.books_detail = {}
    bk_dir = dist_data / 'books'
    if bk_dir.exists():
        for f in bk_dir.glob('*.json'):
            try:
                bk = json.loads(f.read_text(encoding='utf-8'))
                key = bk.get('isbn13','').strip() or bk.get('key','') or f.stem
                d.books_detail[key] = bk
                if bk.get('volume_id'):
                    d.books_detail[f'vol-{bk["volume_id"]}'] = bk
            except Exception:
                pass

    return d


# ============================================================
# SECTION 3: SVG / CHART HELPERS
# ============================================================

def _nice_max(m):
    if m <= 0: return 1
    p = 10 ** math.floor(math.log10(max(m, 1e-9)))
    f = m / p
    if f <= 1: return 1*p
    if f <= 2: return 2*p
    if f <= 2.5: return 2.5*p
    if f <= 5: return 5*p
    return 10*p

def _ticks(n):
    return [0, n/4, n/2, n*3/4, n]

def vbars_svg(data, h=200, fmt=None, cls='bar', line=None, line_fmt=None):
    """Port of JS vbars(). data=[{l, v}, ...]"""
    if not data: return ''
    if fmt is None:
        fmt = lambda v: str(int(v)) if isinstance(v, float) and v == int(v) else str(v)
    W, pl, pr, pt, pb = 560, 36, (40 if line else 8), 14, 26
    iw, ih = W - pl - pr, h - pt - pb
    max_v = max((item['v'] for item in data), default=1)
    nice = _nice_max(max_v)
    bw = iw / len(data)

    s = f'<svg class="c" viewBox="0 0 {W} {h}" role="img">'
    for t in _ticks(nice):
        y = pt + ih - ih * t / nice
        s += (f'<line class="grid" x1="{pl}" x2="{W-pr}" y1="{y:.1f}" y2="{y:.1f}"/>'
              f'<text x="{pl-6}" y="{y+4:.1f}" text-anchor="end">{esc(fmt(t))}</text>')
    for i, item in enumerate(data):
        v = item['v']
        bh = ih * v / nice if nice else 0
        x = pl + i*bw + bw*0.18
        bwi = bw*0.64
        cx = pl + i*bw + bw/2
        s += (f'<rect class="{cls}" x="{x:.1f}" y="{pt+ih-bh:.1f}" '
              f'width="{bwi:.1f}" height="{bh:.1f}" rx="2">'
              f'<title>{esc(item["l"])}: {esc(fmt(v))}</title></rect>')
        s += f'<text x="{cx:.1f}" y="{h-8}" text-anchor="middle">{esc(item["l"])}</text>'
        if len(data) <= 12:
            s += f'<text class="lbl" x="{cx:.1f}" y="{pt+ih-bh-4:.1f}" text-anchor="middle">{esc(fmt(v))}</text>'
    if line:
        lm = _nice_max(max(line) if line else 1)
        pts = [(pl + i*bw + bw/2, pt + ih - ih*v/lm) for i,v in enumerate(line)]
        pts_str = ' '.join(f'{p[0]:.1f},{p[1]:.1f}' for p in pts)
        s += f'<polyline class="line" points="{pts_str}"/>'
        for i,(px,py) in enumerate(pts):
            tt = esc(line_fmt(line[i])) if line_fmt else esc(str(line[i]))
            s += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="var(--violet)"><title>{tt}</title></circle>'
        lf = line_fmt if line_fmt else str
        for t in _ticks(lm):
            ty = pt + ih - ih * t / lm
            s += f'<text x="{W-pr+6}" y="{ty+4:.1f}">{esc(lf(t))}</text>'
    return s + '</svg>'


def hbars_html(rows, max_val=None, cls='', fmt=None):
    """Port of JS hbars(). rows=[{l, v, href?}]"""
    if not rows: return ''
    if fmt is None:
        fmt = lambda v: f'{int(v):,}'.replace(',','.') if isinstance(v,(int,float)) else str(v)
    m = max_val or max((r['v'] for r in rows), default=1) or 1
    items = []
    for r in rows:
        pct = f'{r["v"]/m*100:.1f}%'
        label_html = (f'<a href="{esc(r["href"])}" title="{esc(r["l"])}">{esc(r["l"])}</a>'
                      if r.get('href') else f'<span class="n">{esc(r["l"])}</span>')
        items.append(f'<div class="hbar">{label_html}'
                     f'<div class="t"><i class="{cls}" style="width:{pct}"></i></div>'
                     f'<span class="v">{esc(fmt(r["v"]))}</span></div>')
    return f'<div class="hbars">{"".join(items)}</div>'


def scatter_svg(episodes, h=260):
    """Port of JS scatter()."""
    if not episodes: return ''
    W, pl, pr, pt, pb = 1000, 40, 10, 12, 26
    iw, ih = W-pl-pr, h-pt-pb
    years = sorted(set(int(e['d'][:4]) for e in episodes if e.get('d')))
    if not years: return ''
    t0 = _date(years[0],1,1).toordinal()
    t1 = _date(years[-1]+1,1,1).toordinal()
    all_mins = [e['s']/60 for e in episodes if e.get('s')]
    ymax = _nice_max(max(all_mins) if all_mins else 60)

    def xp(d_str):
        try: return pl + iw*(_date.fromisoformat(d_str).toordinal()-t0)/(t1-t0)
        except: return pl

    s = f'<svg class="c" viewBox="0 0 {W} {h}" role="img" aria-label="Duur per aflevering">'
    for t in _ticks(ymax):
        y = pt+ih-ih*t/ymax
        s += (f'<line class="grid" x1="{pl}" x2="{W-pr}" y1="{y:.1f}" y2="{y:.1f}"/>'
              f'<text x="{pl-6}" y="{y+4:.1f}" text-anchor="end">{int(t)}′</text>')
    for yr in years+[years[-1]+1]:
        try: xyr = pl+iw*(_date(yr,1,1).toordinal()-t0)/(t1-t0)
        except: continue
        s += f'<line class="grid" x1="{xyr:.1f}" x2="{xyr:.1f}" y1="{pt}" y2="{pt+ih}"/>'
        if yr <= years[-1]:
            xmid = xyr + iw/(len(years))/2
            s += f'<text x="{xmid:.1f}" y="{h-8}" text-anchor="middle">{yr}</text>'
    for ep in episodes:
        if not ep.get('d') or not ep.get('s'): continue
        ex, ey = xp(ep['d']), pt+ih-ih*(ep['s']/60)/ymax
        key = ep_key(ep)
        st = ' style="fill:var(--violet)"' if ep.get('f') != 'Gesprek' else ''
        n_str = f'#{ep["n"]} ' if ep.get('n') is not None else ''
        tt = esc(f'{n_str}{ep.get("t","")} — {fmt_dur(ep.get("s",0))}')
        s += (f'<a href="/aflevering/{key}/">'
              f'<circle class="dot" cx="{ex:.1f}" cy="{ey:.1f}" r="4"{st}>'
              f'<title>{tt}</title></circle></a>')
    return s + '</svg>'


def lines_svg(series, labels, h=240, fmt=None, W=1000):
    """Port of JS lines(). series=[{name, v:[]}]"""
    if not series or not labels: return ''
    if fmt is None: fmt = str
    pl, pr, pt, pb = 40, 30, 14, 26
    iw, ih = W-pl-pr, h-pt-pb
    cols = ['var(--violet)','var(--gold-deep)','var(--ink)']
    all_vals = [v for se in series for v in se.get('v',[])]
    ymax = _nice_max(max(all_vals) if all_vals else 1)
    step = iw / max(1, len(labels)-1)
    s = f'<svg class="c" viewBox="0 0 {W} {h}" role="img">'
    for t in _ticks(ymax):
        y = pt+ih-ih*t/ymax
        s += (f'<line class="grid" x1="{pl}" x2="{W-pr}" y1="{y:.1f}" y2="{y:.1f}"/>'
              f'<text x="{pl-6}" y="{y+4:.1f}" text-anchor="end">{esc(fmt(t))}</text>')
    every = max(1, math.ceil(len(labels)/12))
    for i,lbl in enumerate(labels):
        if i % every == 0:
            s += f'<text x="{pl+i*step:.1f}" y="{h-8}" text-anchor="middle">{esc(str(lbl))}</text>'
    for k,se in enumerate(series):
        col = cols[k % len(cols)]
        vals = se.get('v',[])
        pts = [(pl+i*step, pt+ih-ih*v/ymax) for i,v in enumerate(vals)]
        pts_str = ' '.join(f'{p[0]:.1f},{p[1]:.1f}' for p in pts)
        s += f'<polyline fill="none" stroke="{col}" stroke-width="2.5" points="{pts_str}"/>'
        for i,(px,py) in enumerate(pts):
            tt = f'{esc(se.get("name",""))} · {esc(str(labels[i]))}: {esc(fmt(vals[i]))}'
            s += f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{col}"><title>{tt}</title></circle>'
    legend = ''.join(f'<span><i style="background:{cols[k%len(cols)]}"></i>{esc(se.get("name",""))}</span>'
                     for k,se in enumerate(series))
    return s + f'</svg><div class="legend">{legend}</div>'


def timeline_html(eps, years):
    """Port of JS timeline()."""
    if not years: return ''
    t0 = _date(years[0],1,1).toordinal()
    t1 = _date(years[-1]+1,1,1).toordinal()
    def pos(d_str):
        try: return f'{(_date.fromisoformat(d_str).toordinal()-t0)/(t1-t0)*100:.2f}%'
        except: return '0%'
    year_labels = ''.join(f'<span style="left:{pos(str(y)+"-07-01")}">{y}</span>' for y in years)
    dots = []
    for ep in eps:
        if not ep.get('d'): continue
        key = ep_key(ep)
        n_str = f'#{ep["n"]} ' if ep.get('n') is not None else ''
        label = esc(f'{n_str}{ep.get("t","")}')
        dots.append(f'<a href="/aflevering/{key}/" style="left:{pos(ep["d"])}" '
                    f'title="{label} ({esc(fmt_date(ep["d"]))})" aria-label="{esc(ep.get("t",""))}"></a>')
    return f'<div class="tl"><div class="axis"></div>{year_labels}{"".join(dots)}</div>'


# ============================================================
# SECTION 4: HTML COMPONENT HELPERS
# ============================================================

def person_avatar_html(p, size=44):
    k = p['k']
    has_img = p.get('img', False)
    is_host = p.get('role','Gast') != 'Gast'
    cls_ini = f'ini{" host" if is_host else ""}'
    ini = esc(initials(p['name']))
    sty = f'width:{size}px;height:{size}px;font-size:{round(size*24/72)}px;'
    ini_span = f'<span class="{cls_ini}" style="{sty}{"display:none;" if has_img else ""}">{ini}</span>'
    if not has_img:
        return ini_span
    img_cls = f'pimg{" host" if is_host else ""}'
    return (f'<img src="/data/persons/images/{esc(k)}.jpg" class="{img_cls}" '
            f'style="width:{size}px;height:{size}px;border-radius:999px;object-fit:cover;flex-shrink:0" '
            f'alt="{esc(p["name"])}" '
            f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'grid\'">'
            f'{ini_span}')


def social_links_html(socials):
    if not socials: return ''
    links = []
    for k in ('linkedin','twitter','bluesky','website'):
        url = socials.get(k)
        if url:
            icon, label = SOCIAL_ICONS[k]
            links.append(f'<a class="soc-link" href="{esc(url)}" target="_blank" '
                         f'rel="noopener noreferrer" aria-label="{esc(label)}">{icon}</a>')
    return f'<div class="socials">{"".join(links)}</div>' if links else ''


def person_card_html(p):
    n_eps = len(p['eps'])
    ep_w = 'aflevering' if n_eps == 1 else 'afleveringen'
    avatar = person_avatar_html(p, 44)
    return (f'<a class="person" href="/gast/{p["k"]}/" '
            f'data-name="{esc(norm(p["name"]))}" data-count="{n_eps}">'
            f'{avatar}'
            f'<span><b>{esc(p["name"])}</b>'
            f'<span>{esc(p["role"])} · {n_eps} {ep_w}</span></span></a>')


def ep_row_html(ep, highlight_terms=None):
    key = ep_key(ep)
    n = ep.get('n')
    no_html = f'#{n}' if n is not None else '—'
    fmt_val = ep.get('f','')
    badge = f'<span class="badge">{esc(fmt_val)}</span>' if fmt_val and fmt_val != 'Gesprek' else ''
    guest_links = ''
    if ep.get('g'):
        gs = ', '.join(f'<a href="/gast/{slug(g)}/">{esc(g)}</a>' for g in ep['g'])
        guest_links = f' · {gs}'
    desc = ep.get('x') or ep.get('xs') or ''
    snip = esc(desc[:220]) + ('…' if len(desc) > 220 else '')
    theme_chips = ''.join(f'<a class="chip" href="/thema/{slug(t)}/">{esc(t)}</a>'
                          for t in ep.get('th',[]))
    year = ep.get('d','')[:4] if ep.get('d') else ''
    themes_attr = '|'.join(ep.get('th',[]))
    search_text = norm(ep.get('t','') + ' ' + ' '.join(ep.get('g',[])))
    dur_min = str(round(ep.get('s',0)/60))
    return (f'<article class="ep" data-year="{esc(year)}" '
            f'data-themes="{esc(themes_attr)}" data-fmt="{esc(fmt_val)}" '
            f'data-paas="{1 if ep.get("p") else 0}" data-dur-min="{dur_min}" '
            f'data-search="{esc(search_text)}">'
            f'<div class="no">{no_html}</div>'
            f'<div style="min-width:0">'
            f'<h3><a href="/aflevering/{key}/">{esc(ep.get("t",""))}</a>{badge}</h3>'
            f'<div class="meta">{esc(fmt_date(ep.get("d","")))}{guest_links}</div>'
            f'<p class="snip">{snip}</p>'
            f'<div class="chips">{theme_chips}</div>'
            f'</div>'
            f'<div class="dur">{fmt_dur(ep.get("s",0))}</div>'
            f'</article>')


def bk_img_html(isbn13, thumb, w, h=0, r='2px', vol_id=''):
    # All provider fallbacks run at build time. Never expose remote covers to visitors.
    src = next((_COVER_URLS[key] for key in cover_aliases(isbn13, vol_id, thumb)
                if key in _COVER_URLS), '')
    sw, sh = round(w*0.5), round(w*0.5*4/3)
    bk_svg = (f'<svg width="{sw}" height="{sh}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
              f'stroke-width="1.8" style="opacity:.7">'
              f'<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>'
              f'<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>')
    gh = h or round(w*1.37)
    gold = (f'<div style="width:{w}px;height:{gh}px;background:var(--gold);'
            f'border-radius:{r};flex-shrink:0;align-items:center;justify-content:center;'
            f'color:#3e2b16;display:{"none" if src else "flex"}">{bk_svg}</div>')
    if not src:
        return gold
    img_st = f'width:{w}px;{f"height:{h}px;object-fit:cover;" if h else ""}border-radius:{r};flex-shrink:0'
    return (f'<img src="{esc(src)}" alt="" loading="lazy" '
            f'onerror="bkCover(this)" '
            f'style="{img_st}">{gold}')


def bk_thumb_url(vol_id, stored_thumb):
    """Return best Google Books thumbnail URL: stored_thumb first, then construct from vol_id."""
    t = (stored_thumb or '').replace('http:', 'https:').strip()
    if t:
        return t
    v = (vol_id or '').strip()
    if v:
        from urllib.parse import quote as _uq2
        return f'https://books.google.com/books/content?id={_uq2(v)}&printsec=frontcover&img=1&zoom=1&source=gbs_api'
    return ''


def wiki_thumb(url):
    """Normalize Wikimedia thumbnail URLs to 250px (sub-250px sizes often fail to serve)."""
    import re as _re
    if not url:
        return url
    return _re.sub(r'/(\d+)px-', lambda m: f'/{max(250, int(m.group(1)))}px-', url)


def people_panel_html(people, people_dict=None):
    if not people: return ''
    rows = []
    for i,p in enumerate(people):
        sep = ('border-bottom:1px solid var(--rule);margin-bottom:8px;padding-bottom:8px'
               if i < len(people)-1 else '')
        ini = esc(initials(p.get('name','?')))
        p_slug = slug(p.get('name',''))
        agg = (people_dict or {}).get(p_slug, {})
        wiki_img = wiki_thumb(agg.get('img') or p.get('wiki_image') or '')
        if wiki_img:
            img_el = (f'<img src="{esc(wiki_img)}" alt="" loading="lazy" '
                      f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'grid\'" '
                      f'style="width:40px;height:40px;border-radius:999px;object-fit:cover;flex-shrink:0">'
                      f'<span class="ini" style="width:40px;height:40px;font-size:14px;'
                      f'flex-shrink:0;display:none">{ini}</span>')
        else:
            img_el = (f'<span class="ini" style="width:40px;height:40px;font-size:14px;'
                      f'flex-shrink:0">{ini}</span>')
        note_el = (f'<a href="/persoon/{p_slug}/" style="display:block;font-size:12px;'
                   f'color:var(--ink-muted);font-style:italic;margin-top:1px;text-decoration:none">'
                   f'{esc(p["note"])}</a>') if p.get('note') else ''
        ts_btn = ''
        if p.get('start_seconds') is not None:
            ts_btn = (f'<button class="tbtn" type="button" data-seek="{round(p["start_seconds"])}">'
                      f'{ts_fmt(p["start_seconds"])}</button>')
        rows.append(
            f'<div style="display:flex;gap:10px;align-items:flex-start;{sep}">'
            f'<a href="/persoon/{p_slug}/" style="display:contents">{img_el}</a>'
            f'<div style="min-width:0;flex:1">'
            f'<div style="display:flex;align-items:baseline;justify-content:space-between;gap:6px">'
            f'<a href="/persoon/{p_slug}/" style="font-family:Lora,Georgia,serif;font-size:14px;'
            f'font-weight:600;line-height:1.35;color:var(--ink);text-decoration:none">'
            f'{esc(p.get("name",""))}</a>{ts_btn}</div>{note_el}</div></div>')
    return f'<div class="panel"><h3>Besproken figuren</h3>{"".join(rows)}</div>'


def book_panel_html(books):
    if not books: return ''
    rows = []
    for i,b in enumerate(books):
        sep = ('border-bottom:1px solid var(--rule);margin-bottom:10px;padding-bottom:10px'
               if i < len(books)-1 else '')
        title = esc(b.get('canonical_title') or b.get('title') or '')
        author = esc(b.get('canonical_author') or b.get('author') or '')
        note = esc(b.get('note') or '')
        isbn13 = (b.get('isbn13') or '').strip()
        vol_id = (b.get('volume_id') or '').strip()
        bkey = isbn13 if isbn13 else (f'vol-{vol_id}' if vol_id else '')
        cover = bk_img_html(isbn13, bk_thumb_url(vol_id, b.get('thumbnail')), 38, 54, '2px', vol_id=vol_id)
        cover_el = (f'<a href="/boek/{bkey}/" style="line-height:0;flex-shrink:0">{cover}</a>'
                    if bkey else cover)
        title_el = (f'<a href="/boek/{bkey}/" style="color:inherit;text-decoration:none;'
                    f'border-bottom:1px solid var(--rule)">{title}</a>') if bkey else title
        ts_btn = ''
        if b.get('start_seconds') is not None:
            ts_btn = (f'<button class="tbtn" type="button" data-seek="{round(b["start_seconds"])}">'
                      f'{ts_fmt(b["start_seconds"])}</button>')
        rows.append(
            f'<div style="display:flex;gap:10px;{sep}">{cover_el}'
            f'<div style="min-width:0">'
            f'<div style="font-family:Lora,Georgia,serif;font-size:13px;font-weight:600;line-height:1.35">'
            f'{title_el}</div>'
            + (f'<div style="font-size:12px;color:var(--ink-muted);margin-top:2px">{author}</div>' if author else '')
            + (f'<div style="font-size:12px;color:var(--ink-muted);font-style:italic;margin-top:3px">{note}</div>' if note else '')
            + f'{ts_btn}</div></div>')
    return f'<div class="panel"><h3>Besproken boeken</h3>{"".join(rows)}</div>'


def bible_refs_html(refs):
    if not refs: return ''
    items = []
    for i, r in enumerate(refs):
        ref_text = r.get('ref') or r.get('r') or ''
        note = r.get('note') or ''
        if not ref_text: continue
        sep = ('border-bottom:1px solid var(--rule);margin-bottom:8px;padding-bottom:8px'
               if i < len(refs) - 1 else '')
        note_el = (f'<div style="font-size:12px;color:var(--ink-muted);font-style:italic;margin-top:2px">'
                   f'{esc(note)}</div>') if note else ''
        ts_btn = ''
        if r.get('start_seconds') is not None:
            ts_btn = (f'<button class="tbtn" type="button" data-seek="{round(r["start_seconds"])}">'
                      f'{ts_fmt(r["start_seconds"])}</button>')
        parsed = parse_ref(ref_text)
        bvref_attr = ''
        bvv_attr = ''
        if parsed:
            code, ch, v = parsed
            key = f'{code}.{ch}.{v}'
            bvref_attr = f' data-bvref="{key}"'
            verses = _BVDATA.get(key, [])
            if verses:
                bvv_attr = f' data-vv="{esc(json.dumps(verses, ensure_ascii=False))}"'
        items.append(
            f'<div style="{sep}">'
            f'<button class="bref" type="button"{bvref_attr}{bvv_attr}>{esc(ref_text)}</button>'
            f'{note_el}'
            + (f'<div style="margin-top:4px">{ts_btn}</div>' if ts_btn else '')
            + f'</div>')
    if not items: return ''
    return f'<div class="panel"><h3>Bijbelverwijzingen</h3>{"".join(items)}</div>'


def facts_html(stats):
    cells = ''.join(f'<div><b>{esc(s["value"])}</b><span>{esc(s["label"])}</span></div>'
                    for s in stats)
    return f'<div class="facts">{cells}</div>'


def word_cloud_html(word_weights, max_words=25):
    if not word_weights: return ''
    items = sorted(word_weights.items(), key=lambda x: -x[1])[:max_words]
    max_w = items[0][1] if items else 1
    parts = []
    for word, w in items:
        size = 12 + round((w/max_w)*14)
        parts.append(f'<a href="/afleveringen/?q={esc(word)}" style="font-size:{size}px">'
                     f'{esc(word)}</a>')
    return f'<div class="cloud">{"".join(parts)}</div>'


def similar_eps(ep, ep_by_num, reg_eps, n=5):
    """Return up to n similar episodes. Use an.similar if available, else kw overlap."""
    an = ep.get('an') or {}
    if an.get('similar'):
        result = []
        for s in an['similar']:
            other = ep_by_num.get(s.get('n'))
            if other and other is not ep:
                result.append(other)
            if len(result) >= n:
                break
        if result:
            return result
    # Fallback: keyword overlap
    kws = set(ep.get('kw') or [])
    if not kws:
        return []
    scores = [(len(kws & set(e.get('kw') or [])), e)
              for e in reg_eps if e is not ep]
    scores = [(s,e) for s,e in scores if s > 0]
    scores.sort(key=lambda x: -x[0])
    return [e for _,e in scores[:n]]


# ============================================================
# SECTION 5: PAGE SHELL
# ============================================================

_CSS_CACHE = None

def get_css():
    global _CSS_CACHE
    if _CSS_CACHE is None:
        try:
            tmpl = TEMPLATE.read_text(encoding='utf-8')
            m = re.search(r'<style>(.*?)</style>', tmpl, re.DOTALL)
            _CSS_CACHE = m.group(1) if m else ''
        except Exception:
            _CSS_CACHE = ''
    return _CSS_CACHE


_LOGO_SRC = '/assets/logo.jpg'
_WORDMARK_SRC = '/assets/wordmark.png'

NAV_ITEMS = [
    ('afleveringen', 'Afleveringen', '/afleveringen/'),
    ('gasten',       'Gasten',       '/gasten/'),
    ('personen',     'Personen',     '/personen/'),
    ('boeken',       'Boeken',       '/boeken/'),
    ('themas',       "Thema’s", '/themas/'),
    ('statistieken', 'Statistieken', '/statistieken/'),
]


def page_shell(title, content, nav_active='', page_type='', og_meta=None, canonical=None):
    nav_html = ''.join(
        f'<a href="{href}" class="{"on" if key == nav_active else ""}">{esc(label)}</a>'
        for key, label, href in NAV_ITEMS)
    og_html = ''
    if og_meta:
        desc = og_meta.get('description','')
        img  = og_meta.get('image','')
        og_html = (f'<meta property="og:title" content="{esc(title)}">'
                   f'<meta property="og:description" content="{esc(desc)}">'
                   f'<meta name="description" content="{esc(desc)}">'
                   + (f'<meta property="og:image" content="{esc(img)}">' if img else ''))
    can_html = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ''
    page_attr = f' data-page="{page_type}"' if page_type else ''
    return (f'<!DOCTYPE html>\n<html lang="nl">\n'
            f'<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f'<title>{esc(title)} · De Ongelooflijke Podcast</title>\n'
            f'<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
            f'family=Lora:ital,wght@0,500;0,600;0,700;1,500'
            f'&family=Spectral:ital,wght@0,400;0,600;1,400&display=swap">\n'
            f'<link rel="stylesheet" href="/assets/style.css">\n'
            f'<script>function bkCover(el){{var fb=el.dataset.fb||\'\';el.dataset.fb=\'\';if(fb){{el.onerror=function(){{bkCover(el)}};el.onload=null;el.src=fb;}}else{{el.style.display=\'none\';var ic=el.nextElementSibling;if(ic)ic.style.display=\'flex\';}}}}</script>\n'
            f'{og_html}{can_html}'
            f'<script async src="https://plausible.docker.bitfox.nl/js/pa-S1epZutFV1HO5WcDqdEub.js"></script>\n'
            f'<script>window.plausible=window.plausible||function(){{(plausible.q=plausible.q||[]).push(arguments)}},plausible.init='
            f'plausible.init||function(i){{plausible.o=i||{{}}}};plausible.init()</script>\n'
            f'<header class="mast"><div class="wrap">\n'
            f'  <a class="brand" href="/">'
            f'<img src="{_LOGO_SRC}" alt="De Ongelooflijke Podcast">'
            f'<span><b>De Ongelooflijke</b><span>Archief</span></span></a>\n'
            f'  <nav class="main" aria-label="Hoofdmenu">{nav_html}</nav>\n'
            f'</div></header>\n'
            f'<main class="wrap"{page_attr}>\n'
            f'{content}\n'
            f'</main>\n'
            f'<footer class="foot"><div class="wrap">\n'
            f'  <img src="{_WORDMARK_SRC}" alt="De Ongelooflijke · EO">\n'
            f'  <div>Onofficieel archief op basis van de openbare RSS-feed van NPO Luister / EO.<br>'
            f'Gegevens bijgewerkt tot {esc(fmt_date(_BUILT_DATE))}. '
            f'Een initiatief van <a href="https://www.linkedin.com/in/lucasvos/" '
            f'target="_blank" rel="noopener">Lucas Vos</a></div>\n'
            f'</div></footer>\n'
            f'<div id="bpopup" hidden role="dialog" aria-modal="false" aria-label="Bijbelvers"></div>\n'
            f'<script src="/assets/app.js"></script>\n'
            f'</html>')


def write_page(out_path: pathlib.Path, title, content, **kwargs):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = page_shell(title, content, **kwargs)
    out_path.write_text(html, encoding='utf-8')


# ============================================================
# SECTION 6: PAGE GENERATORS
# ============================================================

def build_home(data, out):
    reg = data.reg_eps
    tot = sum(e.get('s', 0) for e in reg)
    latest = sorted(reg, key=lambda e: e.get('d', ''), reverse=True)[:5]

    built_parts = _BUILT_DATE.split('-')
    today_mo = int(built_parts[1]) if len(built_parts) > 1 else 1
    today_dd = int(built_parts[2]) if len(built_parts) > 2 else 1
    today_yr = int(built_parts[0]) if built_parts else 2024

    def day_dist(d_str):
        try:
            parts = d_str.split('-')
            dm = abs((int(parts[1]) - today_mo) * 30 + (int(parts[2]) - today_dd))
            return min(dm, 365 - dm)
        except Exception:
            return 999

    onthisday = [e for e in reg if e.get('d') and
                 int(e['d'][:4]) < today_yr and day_dist(e['d']) <= 4]
    onthisday.sort(key=lambda e: e.get('d', ''), reverse=True)

    top_guests = sorted(
        [g for g in data.guests.values() if g['role'] == 'Gast'],
        key=lambda g: (-len(g['eps']), -g['secs']))[:8]

    n_guests = len([g for g in data.guests.values() if g['role'] == 'Gast'])
    avg_min = round(sum(e.get('s', 0) for e in reg) / len(reg) / 60) if reg else 0

    facts = facts_html([
        {'value': str(len([e for e in reg if e.get('n') is not None])), 'label': 'afleveringen'},
        {'value': str(round(tot / 3600)), 'label': 'uur aan gesprekken'},
        {'value': str(n_guests), 'label': 'verschillende gasten'},
        {'value': f'{avg_min}′', 'label': 'gemiddelde duur'},
    ])

    today_lbl = f'{today_dd} {MONTHS_NL[today_mo - 1]}'
    onthisday_html = ''
    if onthisday:
        rows = ''.join(ep_row_html(e) for e in onthisday[:4])
        onthisday_html = (f'<section><div class="sechead"><h2>Rond deze dag in eerdere jaren</h2>'
                          f'<span class="label">{today_lbl}</span></div>'
                          f'<div class="eps">{rows}</div></section>')

    theme_chips = ''.join(
        f'<a class="chip" href="/thema/{slug(t)}/">{esc(t)} '
        f'<span class="muted">{len(data.theme_eps[t])}</span></a>'
        for t in data.themes[:30])

    reg_keys = [ep_key(e) for e in reg]
    keys_json = json.dumps(reg_keys)

    content = (
        f'<script id="ep-keys" type="application/json">{keys_json}</script>'
        f'<section class="hero"><div>'
        f'<p class="label" style="color:var(--gold-deep)">Sinds april 2019 · EO / NPO Radio 1</p>'
        f'<h1>Alle gesprekken van De Ongelooflijke Podcast, doorzoekbaar.</h1>'
        f'<p class="lede">David Boogerd en theoloog Stefan Paas praten met spraakmakende gasten '
        f'over de vraag of geloof nog relevant is in een steeds ongeloviger Nederland.</p>'
        f'<div class="actions">'
        f'<a class="btn solid" href="/afleveringen/">Doorzoek alle afleveringen</a>'
        f'<button class="btn" id="btn-random" type="button">Verras me</button>'
        f'</div></div>'
        f'<img src="{_LOGO_SRC}" alt=""></section>'
        f'{facts}'
        f'<section><div class="sechead"><h2>Nieuwste afleveringen</h2>'
        f'<a class="ui" href="/afleveringen/">Alle afleveringen -></a></div>'
        f'<div class="eps">{"".join(ep_row_html(e) for e in latest)}</div></section>'
        f'{onthisday_html}'
        f'<section><div class="sechead"><h2>Vaakst te gast</h2>'
        f'<a class="ui" href="/gasten/">Alle gasten -></a></div>'
        f'<div class="people">{"".join(person_card_html(g) for g in top_guests)}</div></section>'
        f'<section><div class="sechead"><h2>Thema’s</h2>'
        f'<a class="ui" href="/themas/">Alle thema’s -></a></div>'
        f'<div class="chips">{theme_chips}</div></section>')

    write_page(out / 'index.html', 'Archief', content,
               nav_active='', page_type='home',
               og_meta={'description': 'Alle afleveringen van De Ongelooflijke Podcast doorzoekbaar.'},
               canonical=f'{_BASE_URL}/')


def build_episode_list(data, out):
    all_eps = data.all_eps
    year_opts = ''.join(f'<option value="{y}">{y}</option>' for y in data.years)
    theme_opts = ''.join(f'<option value="{esc(t)}">{esc(t)}</option>' for t in data.themes)
    fmt_opts = ''.join(f'<option value="{esc(f)}">{esc(f)}</option>'
                       for f in ['Gesprek', 'Live', 'Café', 'Best Of', 'Q&A', 'Spin-off', 'Trailer'])
    ep_rows = ''.join(ep_row_html(e) for e in all_eps)
    content = (
        f'<div class="searchgrid">'
        f'<aside class="filters" aria-label="Filters">'
        f'<div style="margin-bottom:14px">'
        f'<input class="bigq" id="ep-q" type="search" placeholder="Titel, gast of nummer" '
        f'aria-label="Zoekterm" autocomplete="off"></div>'
        f'<fieldset><legend class="label">Jaar</legend>'
        f'<select id="ep-year"><option value="">Alle jaren</option>{year_opts}</select></fieldset>'
        f'<fieldset><legend class="label">Thema</legend>'
        f'<select id="ep-theme"><option value="">Alle thema\'s</option>{theme_opts}</select></fieldset>'
        f'<fieldset><legend class="label">Vorm</legend>'
        f'<select id="ep-fmt"><option value="">Alle vormen</option>{fmt_opts}</select></fieldset>'
        f'<button class="btn" id="ep-reset" type="button">Filters wissen</button>'
        f'</aside>'
        f'<div style="min-width:0">'
        f'<div class="sechead"><h1>Afleveringen</h1>'
        f'<span id="ep-count" class="label">{len(all_eps)} afleveringen</span></div>'
        f'<div class="eps" id="ep-list">{ep_rows}</div>'
        f'</div></div>')
    write_page(out / 'afleveringen' / 'index.html', 'Afleveringen', content,
               nav_active='afleveringen', page_type='episodes',
               canonical=f'{_BASE_URL}/afleveringen/')


def build_guest_list(data, out):
    hosts = sorted([g for g in data.guests.values() if g['role'] != 'Gast'],
                   key=lambda g: (g['role'] != 'Presentator', g['name']))
    guests = sorted([g for g in data.guests.values() if g['role'] == 'Gast'],
                    key=lambda g: (-len(g['eps']), -g['secs']))
    host_cards = ''.join(person_card_html(g) for g in hosts)
    guest_cards = ''.join(person_card_html(g) for g in guests)
    n_total = len(hosts) + len(guests)
    content = (
        f'<h1>Gasten</h1>'
        f'<p class="lede prose muted" style="margin:8px 0 20px">'
        f'De presentator, de vaste gast en {len(guests)} gasten. '
        f'Kies een naam voor alle afleveringen, statistieken en de woorden '
        f'die rond die persoon vallen.</p>'
        f'<section style="margin-bottom:28px">'
        f'<h2 class="label" style="margin-bottom:12px">Vaste gezichten</h2>'
        f'<div class="people">{host_cards}</div></section>'
        f'<div class="sechead" style="margin-bottom:12px">'
        f'<h2>Alle gasten <span class="label muted">({len(guests)})</span></h2></div>'
        f'<div class="ctrl" style="margin-bottom:16px">'
        f'<input id="guest-q" type="search" placeholder="Filter op naam" '
        f'aria-label="Gast zoeken" style="flex:1 1 200px">'
        f'<label class="ui">Sorteer <select id="guest-sort">'
        f'<option value="count">Meeste afleveringen</option>'
        f'<option value="alpha">Achternaam A–Z</option>'
        f'</select></label></div>'
        f'<div class="people" id="plist">{guest_cards}</div>')
    write_page(out / 'gasten' / 'index.html', 'Gasten', content,
               nav_active='gasten', page_type='guests',
               canonical=f'{_BASE_URL}/gasten/')


def build_guest_detail(data, guest, out):
    p = guest
    k = p['k']
    eps_sorted = sorted(p['eps'], key=lambda e: e.get('d', ''), reverse=True)
    is_host = p['role'] != 'Gast'

    co = defaultdict(int)
    for ep in p['eps']:
        for g in ep.get('g', []):
            if g != p['name']:
                co[g] += 1
    co_rows = [{'l': g, 'v': v, 'href': f'/gast/{slug(g)}/'}
               for g, v in sorted(co.items(), key=lambda x: -x[1])[:8]]

    th_counts = defaultdict(int)
    for ep in p['eps']:
        for t in ep.get('th', []):
            th_counts[t] += 1
    th_rows = [{'l': t, 'v': v, 'href': f'/thema/{slug(t)}/'}
               for t, v in sorted(th_counts.items(), key=lambda x: -x[1])[:8]]

    wc = defaultdict(int)
    p_words = set(norm(p['name']).split())
    for ep in p['eps']:
        for kw in ep.get('kw', []):
            if norm(kw) not in p_words:
                wc[kw] += 1
    cloud = word_cloud_html(wc)

    by_year = [{'l': str(y), 'v': len([e for e in p['eps'] if e.get('d', '')[:4] == str(y)])}
               for y in data.years]
    n_eps = len(p['eps'])
    avg_secs = p['secs'] / n_eps if n_eps else 0
    share = n_eps / len(data.reg_eps) * 100 if data.reg_eps else 0

    facts = facts_html([
        {'value': str(n_eps), 'label': 'aflevering' if n_eps == 1 else 'afleveringen'},
        {'value': fmt_hours(p['secs']), 'label': 'uur aan tafel'},
        {'value': f'{round(avg_secs / 60)}′', 'label': 'gem. duur per afl.'},
        {'value': f'{share:.1f}%' if share < 1 else f'{round(share)}%', 'label': 'van alle afleveringen'},
    ])

    first_ep = p['eps'][0] if p['eps'] else None
    last_ep = p['eps'][-1] if p['eps'] else None
    first_link = (f'<a href="/aflevering/{ep_key(first_ep)}/">{fmt_date(first_ep["d"])}</a>'
                  if first_ep else '—')
    last_link = (f'<a href="/aflevering/{ep_key(last_ep)}/">{fmt_date(last_ep["d"])}</a>'
                 if last_ep else '—')
    max_s = max((e.get('s', 0) for e in p['eps']), default=0)
    min_s = min((e.get('s', 0) for e in p['eps'] if e.get('s', 0) > 0), default=0)
    with_paas = len([e for e in p['eps'] if e.get('p')])

    kv_rows = (f'<dt>Eerste keer</dt><dd>{first_link}</dd>'
               f'<dt>Laatste keer</dt><dd>{last_link}</dd>'
               f'<dt>Langste</dt><dd>{fmt_dur(max_s)}</dd>'
               f'<dt>Kortste</dt><dd>{fmt_dur(min_s)}</dd>')
    if not is_host:
        kv_rows += f'<dt>Met Paas</dt><dd>{with_paas} van {n_eps}</dd>'

    tl = timeline_html(p['eps'], data.years)
    chart_html = ''
    if n_eps > 3:
        chart_html = (f'<section style="margin-top:28px"><h2>Afleveringen per jaar</h2>'
                      f'{vbars_svg(by_year, h=170)}</section>')

    ep_limit = 30 if is_host else 200
    ep_rows = ''.join(ep_row_html(e) for e in eps_sorted[:ep_limit])
    more_link = ''
    if is_host and len(eps_sorted) > ep_limit:
        more_link = (f'<p><a class="btn" href="/afleveringen/">Bekijk alle {len(eps_sorted)} '
                     f'in het overzicht</a></p>')

    left = (
        f'<div class="crumb"><a href="/gasten/">Gasten</a> / {esc(p["name"])}</div>'
        f'<div style="display:flex;gap:18px;align-items:center;margin-bottom:12px">'
        f'{person_avatar_html(p, 72)}'
        f'<div><div class="epno">{esc(p["role"])}</div>'
        f'<h1>{esc(p["name"])}</h1>'
        f'{social_links_html(p.get("socials"))}</div></div>'
        + (f'<p class="prose" style="font-size:19px">{esc(p["bio"])}</p>' if p.get('bio') else '')
        + facts
        + f'<section style="margin-top:28px"><h2 style="margin-bottom:4px">Tijdlijn</h2>{tl}</section>'
        + chart_html
        + (f'<section style="margin-top:32px"><div class="sechead">'
           f'<h2>{"Aflevering" if n_eps == 1 else "Alle afleveringen"}</h2>'
           f'<span class="label">nieuwste eerst</span></div>'
           f'<div class="eps">{ep_rows}</div>{more_link}</section>'))

    right = (
        f'<div class="panel"><h3>Gegevens</h3><dl class="kv">{kv_rows}</dl></div>'
        + (f'<div class="panel"><h3>Thema\'s</h3>{hbars_html(th_rows)}</div>' if th_rows else '')
        + (f'<div class="panel"><h3>Samen aan tafel met</h3>{hbars_html(co_rows)}</div>'
           if co_rows else '')
        + (f'<div class="panel"><h3>{"Meest gebruikte" if n_eps > 20 else "Kenmerkende"} woorden</h3>'
           f'{cloud}'
           f'<p class="ui muted" style="font-size:12px;margin:10px 0 0">'
           f'Uit titels en omschrijvingen.</p></div>' if cloud else ''))

    content = (f'<div class="detail"><div style="min-width:0">{left}</div>'
               f'<aside class="side">{right}</aside></div>')
    og_desc = (p.get('bio', '') or '')[:160] or f'{p["role"]} in {n_eps} afleveringen.'
    write_page(out / 'gast' / k / 'index.html', p['name'], content,
               nav_active='gasten', page_type='guest-detail',
               og_meta={'description': og_desc},
               canonical=f'{_BASE_URL}/gast/{k}/')


def build_persons_list(data, out):
    # people.json is a list; filter to persoon/filosoof categories
    persons_raw = [p for p in getattr(data, 'people_list', [])
                   if p.get('c') in ('persoon', 'filosoof')]
    persons = sorted(persons_raw, key=lambda p: -(p.get('x', 0) or 0))

    def pm_avatar(p, size, fs):
        p_slug = p.get('slug') or slug(p.get('n', ''))
        ini = esc(initials(p.get('n', '?')))
        # img field on the agg item is a URL (wiki_image)
        img = p.get('img') or ''
        ini_el = f'<span class="ini" style="width:{size}px;height:{size}px;font-size:{fs}px;flex-shrink:0">{ini}</span>'
        if img and img is not True:
            return (f'<img src="{esc(img)}" alt="" loading="lazy" '
                    f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'grid\'" '
                    f'style="width:{size}px;height:{size}px;border-radius:999px;object-fit:cover;flex-shrink:0">'
                    + ini_el.replace('flex-shrink:0', 'flex-shrink:0;display:none'))
        return ini_el

    def pm_card(p):
        p_slug = p.get('slug') or slug(p.get('n', ''))
        epc = len(p.get('eps', []))
        mx = p.get('mx') or epc
        ep_w = 'aflevering' if epc == 1 else 'afleveringen'
        mx_line = (f'<span class="pm-card-eps" style="color:var(--ink-muted)">{mx}× totaal</span>'
                   if mx > epc else '')
        return (f'<a class="pm-card" href="/persoon/{p_slug}/">'
                f'{pm_avatar(p, 52, 16)}'
                f'<span class="pm-card-name">{esc(p.get("n", ""))}</span>'
                f'<span class="pm-card-eps">{epc} {ep_w}</span>'
                f'{mx_line}</a>')

    def pm_row(p):
        p_slug = p.get('slug') or slug(p.get('n', ''))
        epc = len(p.get('eps', []))
        mx = p.get('mx') or epc
        return (f'<a class="mention-row" href="/persoon/{p_slug}/" '
                f'data-name="{esc(norm(p.get("n", "")))}">'
                f'{pm_avatar(p, 28, 9)}'
                f'<span class="mention-name">{esc(p.get("n", ""))}</span>'
                f'<span class="mention-count num muted">{epc} afl.'
                f'{"" if mx <= epc else f" · {mx}×"}</span></a>')

    top10 = persons[:10]
    rest = persons[10:]
    top_html = f'<div class="pm-cards">{"".join(pm_card(p) for p in top10)}</div>' if top10 else ''
    rest_html = f'<div>{"".join(pm_row(p) for p in rest)}</div>' if rest else ''

    all_yrs = sorted(set(
        yr for p in persons for yr in (p.get('yr') or {}).keys()
    ))
    yr_chips = (''.join(
        f'<button type="button" class="chip" data-yr="{y}">{y}</button>'
        for y in all_yrs))

    content = (
        f'<h1>Personen</h1>'
        f'<p class="lede prose muted" style="margin:8px 0 20px">'
        f'Figuren die in de afleveringen worden genoemd.</p>'
        + (f'<div class="ctrl" style="margin-bottom:4px">'
           f'<div class="chips" style="margin:0" id="pmyears">'
           f'<button type="button" class="chip on" data-yr="">Alle jaren</button>'
           f'{yr_chips}</div></div>' if all_yrs else '')
        + f'<h2 style="margin:20px 0 12px">Meest genoemd</h2>'
        f'<div id="pmtop">{top_html}</div>'
        f'<div class="ctrl" style="margin:28px 0 10px">'
        f'<input id="pm-q" type="search" placeholder="Zoek een persoon…" '
        f'aria-label="Zoek een persoon" style="flex:1 1 220px"></div>'
        f'<div id="pmlist">{rest_html}</div>')
    write_page(out / 'personen' / 'index.html', 'Personen', content,
               nav_active='personen', page_type='persons',
               canonical=f'{_BASE_URL}/personen/')


def build_person_detail(data, p_slug, out):
    detail = data.persons_detail.get(p_slug, {})
    agg = data.people_dict.get(p_slug, {}) if isinstance(data.people_dict, dict) else {}
    if not detail and not agg:
        return
    name = detail.get('name') or agg.get('n') or p_slug
    note = detail.get('note', '') or ''
    wiki_img = detail.get('wiki_image', '') or ''
    wiki_url = detail.get('wiki_url', '') or ''
    wiki_sum = detail.get('wiki_summary', '') or ''
    count = agg.get('x', 0)

    ep_nums = []
    if agg.get('eps'):
        for e in agg['eps']:
            if isinstance(e, dict) and e.get('n') is not None:
                ep_nums.append(e['n'])
            elif isinstance(e, int):
                ep_nums.append(e)
    elif detail.get('eps'):
        ep_nums = [int(x) for x in detail['eps'] if str(x).isdigit()]

    ep_objs = [data.ep_by_num[n] for n in ep_nums if n in data.ep_by_num]
    ep_objs.sort(key=lambda e: e.get('d', ''), reverse=True)

    ini = esc(initials(name))
    if wiki_img:
        img_el = (f'<img src="{esc(wiki_img)}" alt="{esc(name)}" '
                  f'style="width:80px;height:80px;border-radius:999px;object-fit:cover;flex-shrink:0" '
                  f'onerror="this.style.display=\'none\'">')
    else:
        img_el = f'<span class="ini" style="width:80px;height:80px;font-size:28px">{ini}</span>'

    wiki_link = ''
    if wiki_url:
        wiki_link = (f' <a href="{esc(wiki_url)}" target="_blank" rel="noopener" '
                     f'style="font-size:13px;color:var(--violet)">Wikipedia ↗</a>')

    # first / last episode for sidebar
    first_ep_obj = ep_objs[-1] if ep_objs else None
    last_ep_obj = ep_objs[0] if ep_objs else None

    # per-year chart
    yr_data = agg.get('yr', {})
    yr_chart = ''
    if len(ep_objs) > 1 and yr_data:
        by_year = [{'l': str(y), 'v': yr_data.get(str(y), 0) or yr_data.get(y, 0)}
                   for y in data.years]
        yr_chart = (f'<section style="margin-top:28px"><h2>Per jaar</h2>'
                    f'{vbars_svg(by_year, h=160)}</section>')

    # 4-stat facts row
    mention_count = agg.get('mx', count) or count
    facts_row = ''
    if count:
        fc = [
            {'value': str(mention_count), 'label': 'keer genoemd'},
            {'value': str(len(ep_objs)),
             'label': 'aflevering' if len(ep_objs) == 1 else 'afleveringen'},
        ]
        if first_ep_obj:
            d = first_ep_obj.get('d', '')
            fc.append({'value': fmt_date(d).replace(d[:4], '').strip().rstrip(',') if d else '—',
                       'label': 'voor het eerst'})
        if last_ep_obj and last_ep_obj is not first_ep_obj:
            d = last_ep_obj.get('d', '')
            fc.append({'value': fmt_date(d).replace(d[:4], '').strip().rstrip(',') if d else '—',
                       'label': 'voor het laatst'})
        facts_row = facts_html(fc)

    # sidebar: Gegevens
    kv = ''
    if first_ep_obj:
        fn = first_ep_obj.get('n', '')
        fd = fmt_date(first_ep_obj.get('d', ''))
        kv += f'<dt>Eerste keer</dt><dd><a href="/aflevering/{ep_key(first_ep_obj)}/">{esc(fd)}</a></dd>'
    if last_ep_obj and last_ep_obj is not first_ep_obj:
        fn2 = last_ep_obj.get('n', '')
        ld = fmt_date(last_ep_obj.get('d', ''))
        kv += f'<dt>Laatste keer</dt><dd><a href="/aflevering/{ep_key(last_ep_obj)}/">{esc(ld)}</a></dd>'
    if wiki_url:
        kv += f'<dt>Wikipedia</dt><dd><a href="{esc(wiki_url)}" target="_blank" rel="noopener">Open ↗</a></dd>'

    # sidebar: notes (Omschrijvingen)
    notes_list = detail.get('notes', []) or []
    if isinstance(notes_list, str):
        notes_list = [notes_list] if notes_list else []
    notes_html = ''
    if notes_list:
        items = ''.join(f'<li style="font-size:14px;margin-bottom:6px">{esc(n)}</li>'
                        for n in notes_list[:15])
        notes_html = f'<div class="panel"><h3>Omschrijvingen</h3><ul style="margin:0;padding:0 0 0 18px">{items}</ul></div>'

    # sidebar: Meer personen (persons sharing the most episodes)
    more_persons_html = ''
    if isinstance(data.people_list, list):
        my_ep_set = {e.get('n') if isinstance(e, dict) else e for e in agg.get('eps', [])}
        candidates = []
        for other in data.people_list:
            if other.get('slug') == p_slug:
                continue
            if other.get('c') not in ('persoon', 'filosoof'):
                continue
            other_eps = {e.get('n') if isinstance(e, dict) else e for e in other.get('eps', [])}
            shared = len(my_ep_set & other_eps)
            union = len(my_ep_set | other_eps)
            jac = shared / union if union else 0
            candidates.append((jac, other.get('x', 0), other))
        candidates.sort(key=lambda x: (-x[0], -x[1]))
        top_more = [c[2] for c in candidates[:10]]
        if top_more:
            rows = []
            for i, other in enumerate(top_more):
                o_slug = other.get('slug') or slug(other.get('n', ''))
                o_name = other.get('n', '')
                o_epc = len(other.get('eps', []))
                o_img = other.get('img', '') or ''
                o_ini = esc(initials(o_name))
                sep = ('border-bottom:1px solid var(--rule);margin-bottom:8px;padding-bottom:8px'
                       if i < len(top_more) - 1 else '')
                if o_img:
                    img_part = (f'<img src="{esc(o_img)}" alt="" loading="lazy" '
                                f'onerror="this.style.display=\'none\'" '
                                f'style="width:36px;height:36px;border-radius:999px;'
                                f'object-fit:cover;flex-shrink:0">')
                else:
                    img_part = (f'<span class="ini" style="width:36px;height:36px;'
                                f'font-size:13px;flex-shrink:0">{o_ini}</span>')
                rows.append(
                    f'<a href="/persoon/{esc(o_slug)}/" '
                    f'style="display:flex;gap:10px;align-items:center;text-decoration:none;{sep}">'
                    f'{img_part}'
                    f'<span style="min-width:0">'
                    f'<span style="display:block;font-family:Lora,Georgia,serif;font-size:13px;'
                    f'font-weight:600;color:var(--ink)">{esc(o_name)}</span>'
                    f'<span style="display:block;font-size:12px;color:var(--ink-muted)">'
                    f'{o_epc} {"aflevering" if o_epc == 1 else "afleveringen"}</span>'
                    f'</span></a>')
            more_persons_html = (f'<div class="panel"><h3>Meer personen</h3>'
                                 f'{"".join(rows)}</div>')

    sidebar = (
        (f'<div class="panel"><h3>Gegevens</h3><dl class="kv">{kv}</dl></div>' if kv else '')
        + notes_html
        + more_persons_html)

    content = (
        f'<div class="crumb"><a href="/personen/">Personen</a> / {esc(name)}</div>'
        f'<div class="detail"><div style="min-width:0">'
        f'<div style="display:flex;gap:18px;align-items:center;margin-bottom:16px">'
        f'{img_el}<div><div class="epno">Figuur</div>'
        f'<h1 style="margin:4px 0 2px">{esc(name)}</h1>'
        + (f'<p class="prose muted" style="margin:0;font-size:14px">{esc(note)}</p>' if note else '')
        + f'{wiki_link}</div></div>'
        + (f'<div class="prose" style="font-size:16px;margin:0 0 16px">'
           f'{esc(wiki_sum[:800])}{"…" if len(wiki_sum) > 800 else ""}</div>'
           if wiki_sum else '')
        + facts_row
        + yr_chart
        + (f'<section style="margin-top:28px"><div class="sechead"><h2>Afleveringen</h2>'
           f'<span class="label">nieuwste eerst</span></div>'
           f'<div class="eps">{"".join(ep_row_html(e) for e in ep_objs)}</div></section>'
           if ep_objs else '')
        + f'</div><aside class="side">{sidebar}</aside></div>')

    og_desc = note or f'{esc(name)} besproken in De Ongelooflijke Podcast.'
    write_page(out / 'persoon' / p_slug / 'index.html', name, content,
               nav_active='personen', page_type='persons-detail',
               og_meta={'description': og_desc},
               canonical=f'{_BASE_URL}/persoon/{p_slug}/')


def build_books_list(data, out):
    books = sorted(data.books_list, key=lambda b: -(b.get('x', 0) or 0))

    def bk_row(b):
        bkey = b.get('book_key', '') or b.get('isbn13', '') or slug(b.get('n', ''))
        title = esc(b.get('n', '') or b.get('title', ''))
        author = esc(b.get('author', ''))
        count = b.get('x', 0)
        isbn_key = str(bkey) if re.match(r'^\d{13}$', str(bkey)) else ''
        vol_key = str(bkey)[4:] if str(bkey).startswith('vol-') else ''
        cover = bk_img_html(isbn_key,
                            bk_thumb_url(vol_key, b.get('bk_thumb') or b.get('thumbnail') or ''),
                            40, 56, '3px', vol_id=vol_key)
        return (f'<a class="mention-row" href="/boek/{esc(bkey)}/" '
                f'data-title="{esc(norm(b.get("n", "") or ""))}" '
                f'style="align-items:center">'
                f'{cover}'
                f'<span class="mention-name" style="flex:1 1 0;min-width:0">'
                f'<b>{title}</b>'
                + (f'<span style="display:block;font-size:12px;color:var(--ink-muted)">{author}</span>'
                   if author else '')
                + f'</span>'
                f'<span class="mention-count num muted">{count}×</span>'
                f'</a>')

    def bk_card(b):
        bkey = b.get('book_key', '') or slug(b.get('n', ''))
        isbn_key = str(bkey) if re.match(r'^\d{13}$', str(bkey)) else ''
        vol_key = str(bkey)[4:] if str(bkey).startswith('vol-') else ''
        cover = bk_img_html(isbn_key, bk_thumb_url(vol_key, b.get('bk_thumb') or ''), 64, 90, '4px', vol_id=vol_key)
        title = esc(b.get('n', ''))
        author = esc(b.get('author', ''))
        epc = len(b.get('eps', []))
        ep_w = 'aflevering' if epc == 1 else 'afleveringen'
        return (f'<a class="pm-card" href="/boek/{esc(bkey)}/" '
                f'style="border:1px solid var(--rule)">'
                f'{cover}'
                f'<b style="font-family:Lora,Georgia,serif;font-size:13px;line-height:1.3;'
                f'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;'
                f'overflow:hidden;width:100%">{title}</b>'
                + (f'<span style="font-size:12px;color:var(--ink-muted);width:100%;'
                   f'display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;'
                   f'overflow:hidden">{author}</span>' if author else '')
                + f'<span class="pm-card-eps">{epc} {ep_w}</span></a>')

    top10 = books[:10]
    rest = books[10:]
    top_html = f'<div class="pm-cards">{"".join(bk_card(b) for b in top10)}</div>' if top10 else ''
    rows_html = ''.join(bk_row(b) for b in rest)

    content = (
        f'<h1>Boeken</h1>'
        f'<p class="lede prose muted" style="margin:8px 0 20px">'
        f'Boeken die in afleveringen worden besproken of aanbevolen.</p>'
        f'<h2 style="margin:20px 0 12px">Meest besproken</h2>'
        f'{top_html}'
        f'<div class="ctrl" style="margin:28px 0 10px">'
        f'<input id="bk-q" type="search" placeholder="Zoek een boek of auteur…" '
        f'aria-label="Zoek een boek" style="flex:1 1 220px"></div>'
        f'<div>{rows_html}</div>')
    write_page(out / 'boeken' / 'index.html', 'Boeken', content,
               nav_active='boeken', page_type='books',
               canonical=f'{_BASE_URL}/boeken/')


def build_book_detail(data, book_agg, out):
    bkey = book_agg.get('book_key', '') or book_agg.get('isbn13', '') or slug(book_agg.get('n', ''))
    if not bkey:
        return
    detail = data.books_detail.get(bkey, {})
    title = detail.get('title') or book_agg.get('n', '')
    author = detail.get('author') or book_agg.get('author', '')
    desc = strip_html(detail.get('description', ''))
    # book_key IS the isbn13 (13-digit key); isbn13 field in agg is usually None
    isbn13 = detail.get('isbn13', '') or (
        str(bkey) if re.match(r'^\d{13}$', str(bkey)) else '')
    isbn10 = detail.get('isbn10', '')
    vol_id = detail.get('volume_id', '') or (str(bkey)[4:] if str(bkey).startswith('vol-') else '')
    thumb = bk_thumb_url(vol_id,
                         detail.get('thumbnail_large') or detail.get('thumbnail')
                         or book_agg.get('bk_thumb', ''))
    publisher = detail.get('publisher', '')
    pub_year = detail.get('published_year', '')
    pages = detail.get('page_count', 0)
    gb_url = detail.get('google_books_url', '')
    count = book_agg.get('x', 0)

    eps_data = sorted(book_agg.get('eps', []), key=lambda e: e.get('d', '') if isinstance(e, dict) else '')
    ep_objs = []
    for e in eps_data:
        n = e.get('n') if isinstance(e, dict) else e
        if n in data.ep_by_num:
            ep_objs.append(data.ep_by_num[n])
    ep_objs.sort(key=lambda e: e.get('d', ''), reverse=True)

    cover = bk_img_html(isbn13, thumb, 90, 123, '4px', vol_id=vol_id)
    buy_q = isbn13 or bkey or title
    from urllib.parse import quote as _uq
    _bol_search = f'https://www.bol.com/nl/nl/s/?searchtext={_uq(str(buy_q))}'
    bol_url = f'https://partner.bol.com/click/click?&t=url&s=1562349&url={_uq(_bol_search)}&f=txl'

    kv_rows = ''
    if isbn13:
        kv_rows += f'<dt>ISBN-13</dt><dd style="font-variant-numeric:tabular-nums">{esc(isbn13)}</dd>'
    if isbn10:
        kv_rows += f'<dt>ISBN-10</dt><dd style="font-variant-numeric:tabular-nums">{esc(isbn10)}</dd>'
    if publisher:
        kv_rows += f'<dt>Uitgever</dt><dd>{esc(publisher)}</dd>'
    if pub_year:
        kv_rows += f'<dt>Jaar</dt><dd>{esc(str(pub_year))}</dd>'
    if pages:
        kv_rows += f'<dt>Pagina\'s</dt><dd>{pages}</dd>'

    yr_data = book_agg.get('yr', {})
    yr_chart = ''
    if len(ep_objs) > 1 and yr_data:
        by_year = [{'l': str(y), 'v': yr_data.get(str(y), 0) or yr_data.get(y, 0)}
                   for y in data.years]
        yr_chart = (f'<section style="margin-top:28px"><h2>Per jaar</h2>'
                    f'{vbars_svg(by_year, h=160)}</section>')

    left = (
        f'<div class="crumb"><a href="/boeken/">Boeken</a> / {esc(title)}</div>'
        f'<div style="display:flex;gap:18px;align-items:flex-start;margin-bottom:16px">'
        f'{cover}<div style="min-width:0"><div class="epno">Boek</div>'
        f'<h1 style="margin:4px 0 6px">{esc(title)}</h1>'
        + (f'<div style="font-size:17px;color:var(--ink-muted)">{esc(author)}</div>'
           if author else '')
        + f'</div></div>'
        + (f'<div class="prose" style="font-size:16px;margin:0 0 20px">{esc(desc)}</div>'
           if desc else '')
        + facts_html([
            {'value': str(count), 'label': 'keer besproken'},
            {'value': str(len(ep_objs)),
             'label': 'aflevering' if len(ep_objs) == 1 else 'afleveringen'},
        ])
        + yr_chart
        + (f'<section style="margin-top:28px"><div class="sechead"><h2>Afleveringen</h2></div>'
           f'<div class="eps">{"".join(ep_row_html(e) for e in ep_objs)}</div></section>'
           if ep_objs else ''))

    # Meer boeken: books sharing the most episodes with this one
    my_ep_set = {e.get('n') if isinstance(e, dict) else e for e in book_agg.get('eps', [])}
    more_books = []
    for other in data.books_list:
        other_key = other.get('book_key', '') or slug(other.get('n', ''))
        if other_key == bkey or not other_key:
            continue
        other_eps = {e.get('n') if isinstance(e, dict) else e for e in other.get('eps', [])}
        shared = len(my_ep_set & other_eps)
        union = len(my_ep_set | other_eps)
        jac = shared / union if union else 0
        more_books.append((jac, other.get('x', 0), other, other_key))
    more_books.sort(key=lambda x: (-x[0], -x[1]))
    more_books = more_books[:10]

    right = ''
    if kv_rows:
        right += f'<div class="panel"><h3>Gegevens</h3><dl class="kv">{kv_rows}</dl></div>'
    right += (f'<div class="panel"><h3>Kopen</h3>'
              f'<a class="btn solid" href="{esc(bol_url)}" target="_blank" rel="noopener" '
              f'style="display:block;text-align:center">Zoek op bol.com</a>'
              + f'</div>')
    if more_books:
        rows_mb = []
        for i, (_, _, other, okey) in enumerate(more_books):
            o_title = esc(other.get('n', ''))
            o_author = esc(other.get('author', ''))
            o_isbn = str(okey) if re.match(r'^\d{13}$', str(okey)) else ''
            o_vol = str(okey)[4:] if str(okey).startswith('vol-') else ''
            o_cover = bk_img_html(o_isbn, bk_thumb_url(o_vol, other.get('bk_thumb') or ''), 34, 48, '2px', vol_id=o_vol)
            sep = ('border-bottom:1px solid var(--rule);margin-bottom:8px;padding-bottom:8px'
                   if i < len(more_books) - 1 else '')
            rows_mb.append(
                f'<a href="/boek/{esc(okey)}/" '
                f'style="display:flex;gap:10px;text-decoration:none;{sep}">'
                f'{o_cover}'
                f'<span style="min-width:0">'
                f'<span style="display:block;font-family:Lora,Georgia,serif;font-size:13px;'
                f'font-weight:600;line-height:1.35;color:var(--ink)">{o_title}</span>'
                + (f'<span style="display:block;font-size:12px;color:var(--ink-muted);'
                   f'margin-top:2px">{o_author}</span>' if o_author else '')
                + f'</span></a>')
        right += f'<div class="panel"><h3>Meer boeken</h3>{"".join(rows_mb)}</div>'

    content = (f'<div class="detail"><div style="min-width:0">{left}</div>'
               f'<aside class="side">{right}</aside></div>')
    write_page(out / 'boek' / bkey / 'index.html', title, content,
               nav_active='boeken', page_type='book-detail',
               canonical=f'{_BASE_URL}/boek/{bkey}/')


def build_themes_list(data, out):
    cards = []
    for t in data.themes:
        t_slug = slug(t)
        t_eps = data.theme_eps[t]
        by_year = [{'l': str(y), 'v': len([e for e in t_eps if e.get('d', '')[:4] == str(y)])}
                   for y in data.years]
        mini_chart = vbars_svg(by_year, h=120, cls='bar')
        hrs = fmt_hours(sum(e.get('s', 0) for e in t_eps))
        cards.append(
            f'<a href="/thema/{t_slug}/" class="panel" '
            f'style="text-decoration:none;color:var(--ink);display:block">'
            f'<h3 style="margin-bottom:2px">{esc(t)}</h3>'
            f'<div class="ui muted" style="font-size:14px">'
            f'{len(t_eps)} afleveringen · {hrs} uur</div>'
            f'{mini_chart}</a>')
    content = (
        f'<h1>Thema\'s</h1>'
        f'<p class="prose muted" style="margin:8px 0 22px">Elke aflevering is automatisch '
        f'ingedeeld bij maximaal vier thema\'s.</p>'
        f'<div class="charts">{"".join(cards)}</div>')
    write_page(out / 'themas' / 'index.html', "Thema's", content,
               nav_active='themas', canonical=f'{_BASE_URL}/themas/')


def build_theme_detail(data, theme, out):
    t_slug = slug(theme)
    t_eps = sorted(data.theme_eps[theme], key=lambda e: e.get('d', ''), reverse=True)
    n = len(t_eps)
    reg_eps = data.reg_eps
    hrs = fmt_hours(sum(e.get('s', 0) for e in t_eps))

    # percentage per year (like the SPA)
    by_year = []
    for y in data.years:
        all_in_year = len([e for e in reg_eps if e.get('d', '')[:4] == str(y)])
        theme_in_year = len([e for e in t_eps if e.get('d', '')[:4] == str(y)])
        pct = round(theme_in_year / all_in_year * 100) if all_in_year else 0
        by_year.append({'l': str(y), 'v': pct})
    chart = vbars_svg(by_year, h=180, fmt=lambda v: f'{v}%')

    g_counts = defaultdict(int)
    for ep in t_eps:
        for g in ep.get('g', []):
            g_counts[g] += 1
    g_rows = [{'l': g, 'v': v, 'href': f'/gast/{slug(g)}/'}
              for g, v in sorted(g_counts.items(), key=lambda x: -x[1])[:10]]

    # word cloud from episode keywords
    word_counts = defaultdict(int)
    for ep in t_eps:
        for kw in (ep.get('kw') or []):
            word_counts[kw.lower()] += 1
    top_words = sorted(word_counts.items(), key=lambda x: -x[1])[:30]
    wmax = top_words[0][1] if top_words else 1
    cloud_html = ''
    if top_words:
        words_html = ''.join(
            f'<span style="font-size:{13 + 13 * c / wmax:.1f}px;'
            f'color:var(--ink);padding:2px 4px">{esc(w)}</span>'
            for w, c in top_words)
        cloud_html = (f'<div class="panel"><h3>Kenmerkende woorden</h3>'
                      f'<div class="cloud" style="line-height:1.9">{words_html}</div></div>')

    sidebar = ''
    if g_rows:
        sidebar += f'<div class="panel"><h3>Gasten binnen dit thema</h3>{hbars_html(g_rows)}</div>'
    sidebar += cloud_html

    left = (
        f'<div class="crumb"><a href="/themas/">Thema\'s</a> / {esc(theme)}</div>'
        f'<h1>{esc(theme)}</h1>'
        f'<p class="ui muted">{n} {"aflevering" if n == 1 else "afleveringen"} · {hrs} uur</p>'
        f'<section style="margin-top:22px"><h2>Aandeel per jaar</h2>'
        f'<p class="ui muted" style="font-size:13px;margin:0 0 8px">'
        f'Percentage van de afleveringen in dat jaar.</p>'
        f'{chart}</section>'
        f'<section style="margin-top:24px"><div class="sechead"><h2>Afleveringen</h2></div>'
        f'<div class="eps">{"".join(ep_row_html(e) for e in t_eps)}</div></section>')

    content = (f'<div class="detail"><div style="min-width:0">{left}</div>'
               f'<aside class="side">{sidebar}</aside></div>')
    write_page(out / 'thema' / t_slug / 'index.html', theme, content,
               nav_active='themas', page_type='theme-detail',
               canonical=f'{_BASE_URL}/thema/{t_slug}/')


def build_stats(data, out):
    reg = data.reg_eps

    def nl_num(n):
        return f"{int(n):,}".replace(",", ".")

    # --- Facts ---
    tot_secs = sum(e.get("s", 0) for e in reg)
    tot_hrs = round(tot_secs / 3600)

    dated = sorted([e for e in reg if e.get("d") and e.get("n") is not None],
                   key=lambda e: e["d"])
    gaps = []
    for i in range(1, len(dated)):
        try:
            d0 = _date.fromisoformat(dated[i-1]["d"])
            d1 = _date.fromisoformat(dated[i]["d"])
            gaps.append((d1 - d0).days)
        except Exception:
            pass
    gaps.sort()
    median = gaps[len(gaps) // 2] if gaps else 0

    paas_pct = round(len([e for e in reg if e.get("p")]) / len(reg) * 100) if reg else 0
    guest_only = [g for g in data.guests.values() if g["role"] == "Gast"]
    return_pct = round(len([g for g in guest_only if len(g["eps"]) > 1]) / max(len(guest_only), 1) * 100)

    # --- Per-year data ---
    per_year = {y: [e for e in reg if e.get("d", "")[:4] == str(y)] for y in data.years}

    by_year_count = [{"l": str(y), "v": len(per_year[y])} for y in data.years]
    avg_min_line = [
        round(sum(e.get("s", 0) for e in per_year[y]) / len(per_year[y]) / 60)
        if per_year[y] else 0
        for y in data.years
    ]
    by_year_hours = [
        {"l": str(y), "v": round(sum(e.get("s", 0) for e in per_year[y]) / 3600)}
        for y in data.years
    ]

    # --- Guests charts ---
    actual_guests = sorted(guest_only, key=lambda g: (-len(g["eps"]), -g["secs"]))[:12]
    guest_rows = [{"l": g["name"], "v": len(g["eps"]), "href": f"/gast/{g['k']}/"} for g in actual_guests]
    top_time = sorted(guest_only, key=lambda g: -g["secs"])[:12]
    time_rows = [{"l": g["name"], "v": round(g["secs"] / 3600, 1), "href": f"/gast/{g['k']}/"}
                 for g in top_time]

    # --- Heatmap ---
    heat = []
    for t in data.themes:
        vals = [
            len([e for e in per_year.get(y, []) if t in e.get("th", [])]) / len(per_year[y])
            if per_year.get(y) else 0
            for y in data.years
        ]
        heat.append((t, vals))
    hmax = max((v for _, vals in heat for v in vals), default=1) or 1

    heat_rows = []
    for t, vals in heat:
        t_slug_v = slug(t)
        cells = ""
        for v in vals:
            pct = round(v / hmax * 100) if hmax else 0
            text_color = "#3e2b16" if hmax and v / hmax > 0.55 else "var(--ink-muted)"
            cells += (f'<td><div style="background:color-mix(in srgb,var(--gold) {pct}%,'
                      f'var(--parchment-2));color:{text_color}" title="{round(v*100)}%">'
                      f'{round(v*100)}</div></td>')
        heat_rows.append(f'<tr><th><a href="/thema/{t_slug_v}/" style="color:var(--ink)">{esc(t)}</a></th>{cells}</tr>')
    year_headers = "".join(f"<th>{y}</th>" for y in data.years)
    heat_html = (f'<div class="scroll"><table class="heat"><thead><tr><th></th>{year_headers}</tr></thead>'
                 f'<tbody>{"".join(heat_rows)}</tbody></table></div>')

    # --- Verschijningsdag ---
    day_abbr = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
    day_order = [1, 2, 3, 4, 5, 6, 0]
    wd_counts = []
    for i, d in enumerate(day_order):
        count = 0
        for e in reg:
            if e.get("d"):
                try:
                    count += int(_date.fromisoformat(e["d"]).isoweekday() % 7 == d)
                except Exception:
                    pass
        wd_counts.append({"l": day_abbr[i], "v": count})

    # --- Records ---
    sorted_ns = sorted([e for e in reg if e.get("f") != "Spin-off" and e.get("s")],
                       key=lambda e: -e["s"])
    longest = sorted_ns[0] if sorted_ns else None
    gesprek_eps = sorted([e for e in reg if e.get("f") == "Gesprek" and e.get("s")],
                         key=lambda e: e["s"])
    shortest_gesprek = gesprek_eps[0] if gesprek_eps else None
    all_sorted_desc = sorted(reg, key=lambda e: len((e.get("x") or e.get("xs") or "")),
                             reverse=True)
    longest_desc = all_sorted_desc[0] if all_sorted_desc else None

    rec_counts_s: dict = defaultdict(int)
    for e in reg:
        for n in e.get("r", []):
            rec_counts_s[n] += 1
    most_rec_ep = most_rec_count_v = None
    if rec_counts_s:
        top_n = max(rec_counts_s, key=lambda n: rec_counts_s[n])
        most_rec_ep = data.ep_by_num.get(top_n)
        most_rec_count_v = rec_counts_s[top_n]

    def ep_link(e):
        if not e:
            return '<span class="muted">—</span>'
        k = ep_key(e)
        label = (f'#{e["n"]} ' if e.get("n") is not None else "") + (e.get("t") or "")
        return f'<a href="/aflevering/{k}/">{esc(label)}</a>'

    records_html = '<div class="hbars" style="gap:10px;font-size:15px">'
    if longest:
        records_html += (f'<div><span class="label">Langste</span><br>'
                         f'{ep_link(longest)} <span class="muted">· {fmt_dur(longest["s"])}</span></div>')
    if shortest_gesprek:
        records_html += (f'<div><span class="label">Kortste gesprek</span><br>'
                         f'{ep_link(shortest_gesprek)} <span class="muted">· {fmt_dur(shortest_gesprek["s"])}</span></div>')
    if longest_desc:
        desc_words = len((longest_desc.get("x") or longest_desc.get("xs") or "").split())
        records_html += (f'<div><span class="label">Langste omschrijving</span><br>'
                         f'{ep_link(longest_desc)} <span class="muted">· {nl_num(desc_words)} woorden</span></div>')
    if most_rec_ep:
        records_html += (f'<div><span class="label">Meest aangeraden door de makers</span><br>'
                         f'{ep_link(most_rec_ep)} <span class="muted">· {most_rec_count_v}× genoemd</span></div>')
    records_html += "</div>"

    # --- Intro ---
    oldest = min(reg, key=lambda e: e.get("d", "9999"))
    newest = max(reg, key=lambda e: e.get("d", "0000"))
    intro = (f'<p class="prose muted" style="margin:8px 0 6px">Berekend uit {len(reg)} afleveringen '
             f'van {fmt_date(oldest.get("d",""))} tot {fmt_date(newest.get("d",""))}.</p>')

    content = (
        "<h1>Statistieken</h1>"
        + intro
        + facts_html([
            {"value": nl_num(tot_hrs), "label": "uur in totaal"},
            {"value": str(median), "label": "dagen tussen afleveringen (mediaan)"},
            {"value": f"{paas_pct}%", "label": "met Stefan Paas aan tafel"},
            {"value": f"{return_pct}%", "label": "van de gasten kwam terug"},
        ])
        + '<section><div class="charts">'
        + ('<div class="chart"><h3>Afleveringen per jaar</h3>'
           '<p class="note">Staven: aantal afleveringen. Lijn: gemiddelde duur in minuten (rechteras).</p>'
           + vbars_svg(by_year_count, line=avg_min_line, line_fmt=lambda v: str(round(v)) + "′")
           + "</div>")
        + ('<div class="chart"><h3>Uren per jaar</h3>'
           '<p class="note">Totale speelduur van alle afleveringen in dat jaar.</p>'
           + vbars_svg(by_year_hours, cls="bar2", fmt=lambda v: str(int(v)) + " u")
           + "</div>")
        + ('<div class="chart wide"><h3>Duur van elke aflevering</h3>'
           '<p class="note">Elke stip is een aflevering; paars zijn live-afleveringen, Café, Best Of '
           'en andere specials.</p>'
           '<div class="scroll"><div style="min-width:640px">'
           + scatter_svg(reg)
           + "</div></div></div>")
        + ('<div class="chart"><h3>Vaakst te gast</h3>'
           '<p class="note">Aantal afleveringen, zonder presentator en vaste gast.</p>'
           + hbars_html(guest_rows)
           + "</div>")
        + ('<div class="chart"><h3>Meeste tijd aan tafel</h3>'
           '<p class="note">Opgetelde duur van de afleveringen, in uren.</p>'
           + hbars_html(time_rows, cls="v", fmt=lambda v: f"{v:.1f}".replace(".", ","))
           + "</div>")
        + ('<div class="chart wide"><h3>Thema’s door de jaren heen</h3>'
           '<p class="note">Aandeel van de afleveringen per jaar waarin het thema voorkomt.</p>'
           + heat_html
           + "</div>")
        + '<div class="chart wide" id="words"></div>'
        + ('<div class="chart wide" id="trend">'
           '<h3>Woordtrend</h3>'
           '<p class="note">Percentage afleveringen per jaar waarin het woord in titel of omschrijving staat. '
           'Tot drie woorden, gescheiden door komma’s.</p>'
           '<form class="ctrl" id="tf">'
           '<input id="t-in" value="trump, oorlog, ai" aria-label="Woorden" style="flex:1 1 260px">'
           '<button class="btn" type="submit">Vergelijk</button></form>'
           "</div>")
        + ('<div class="chart"><h3>Verschijningsdag</h3>'
           '<p class="note">Op welke weekdag afleveringen uitkwamen.</p>'
           + vbars_svg(wd_counts, h=180)
           + "</div>")
        + ('<div class="chart"><h3>Records</h3>'
           + records_html
           + "</div>")
        + "</div></section>"
    )
    write_page(out / "statistieken" / "index.html", "Statistieken", content,
               nav_active="statistieken", page_type="stats",
               canonical=f"{_BASE_URL}/statistieken/")

def build_episode_detail(data, ep, out):
    import datetime as _dt
    key = ep_key(ep)
    an = ep.get('an') or {}
    n = ep.get('n')
    fmt = ep.get('f', 'Gesprek')

    # Trivia
    trivia = []
    if fmt != 'Trailer':
        yr_str = ep.get('d', '')[:4]
        yr_eps = sorted([e for e in data.reg_eps if e.get('d', '')[:4] == yr_str],
                        key=lambda e: -(e.get('s', 0)))
        rank = next((i + 1 for i, e in enumerate(yr_eps) if ep_key(e) == key), None)
        if rank and yr_eps:
            lbl = ('langste' if rank == 1 else
                   ('kortste' if rank == len(yr_eps) else f'{rank}e langste'))
            trivia.append(f'De {lbl} van de {len(yr_eps)} afleveringen uit {yr_str}.')
        if ep.get('d'):
            try:
                wd = _dt.date.fromisoformat(ep['d']).isoweekday() % 7
                trivia.append(f'Uitgebracht op een {DAYS_NL[wd]}.')
            except Exception:
                pass
        for g in ep.get('g', []):
            guest_obj = data.guests.get(slug(g))
            if not guest_obj:
                continue
            g_eps = sorted(guest_obj['eps'], key=lambda e: e.get('d', ''))
            idx = next((i for i, e in enumerate(g_eps) if ep_key(e) == key), None)
            if idx is not None and len(g_eps) > 1:
                trivia.append(f'{"Eerste" if idx == 0 else f"{idx + 1}e"} van '
                               f'{len(g_eps)} optredens van {esc(g)}.')
        if not ep.get('p') and fmt == 'Gesprek':
            trivia.append('Een van de zeldzame afleveringen zonder Stefan Paas.')

    rel_eps = [data.ep_by_num[nr] for nr in (ep.get('r') or []) if nr in data.ep_by_num]
    sim_eps = similar_eps(ep, data.ep_by_num, data.reg_eps)
    sim_is_llm = bool(an.get('similar'))

    idx = next((i for i, e in enumerate(data.reg_eps) if ep_key(e) == key), None)
    newer = data.reg_eps[idx - 1] if idx is not None and idx > 0 else None
    older = data.reg_eps[idx + 1] if idx is not None and idx < len(data.reg_eps) - 1 else None

    cast = [{'name': 'David Boogerd', 'role': 'Presentator'}]
    if ep.get('p'):
        cast.append({'name': 'Stefan Paas', 'role': 'Vaste gast'})
    cast += [{'name': g, 'role': 'Gast'} for g in ep.get('g', [])]

    def cast_card(c):
        g_obj = data.guests.get(slug(c['name']))
        p = g_obj or {'name': c['name'], 'k': slug(c['name']), 'role': c['role'],
                      'eps': [], 'img': False}
        n_ep = len(p.get('eps', []))
        ep_w = 'aflevering' if n_ep == 1 else 'afleveringen'
        avatar = person_avatar_html(p, 44)
        return (f'<a class="person" href="/gast/{p["k"]}/">'
                f'{avatar}'
                f'<span><b>{esc(p["name"])}</b>'
                f'<span>{esc(c["role"])} · {n_ep} {ep_w}</span></span></a>')

    # Tabs
    # Description prose (Omschrijving van de makers)
    desc = ep.get('x', '') or ep.get('xs', '') or ''
    desc_html = ('<div class="prose">'
                 + ''.join(f'<p>{esc(p)}</p>' for p in desc.split('\n') if p.strip())
                 + '</div>') if desc else ''

    # In het kort (only if analysis exists)
    has_analysis = bool(an.get('summary_tldr') or an.get('summary_points'))
    if has_analysis:
        tldr_html = f'<h2>In het kort</h2><p class="tldr">{esc(an.get("summary_tldr", ""))}</p>'
        if an.get('summary_points'):
            tldr_html += ('<h2>Kernpunten</h2><ul class="points">'
                          + ''.join(f'<li>{esc(pt)}</li>' for pt in an['summary_points'])
                          + '</ul>')
    else:
        tldr_html = ''

    # Wie is wanneer aan het woord - placeholder for river + spk legend (filled by app.js)
    river_placeholder = (
        '<h2>Wie is wanneer aan het woord</h2>'
        '<div class="river" data-river-pending '
        'style="height:36px;background:var(--parchment-3);border-radius:4px"></div>'
        '<div class="spk" data-spk-pending style="display:flex;gap:14px;'
        'flex-wrap:wrap;margin-top:10px;font-size:14px"></div>'
    )

    # Hoogtepunten \u2014 sort by start_seconds, use note as label, wrap text in curly quotes
    hl_html = ''
    if an.get('highlights'):
        sorted_hls = sorted(
            an['highlights'],
            key=lambda h: h.get('start_seconds') if h.get('start_seconds') is not None else 999999
        )[:8]
        items = []
        for hl in sorted_hls:
            ts_btn = ''
            if hl.get('start_seconds') is not None:
                ts_btn = (f'<button class="tbtn" type="button" '
                          f'data-seek="{round(hl["start_seconds"])}">'
                          f'{ts_fmt(hl["start_seconds"])}</button>')
            speaker = esc(hl.get('speaker', ''))
            note = esc(hl.get('note', '') or 'Hoogtepunt')
            lbl = f'{note}{f" \u00b7 {speaker}" if speaker else ""}'
            text = hl.get('text', '')
            text_html = f'\u2018{esc(text)}\u2019' if text else ''
            items.append(f'<li>{ts_btn}<div><span class="label">{lbl}</span>'
                         f'<p>{text_html}</p></div></li>')
        hl_html = (f'<h2>Hoogtepunten</h2>'
                   f'<ol class="hl" id="hl-list">{"".join(items)}</ol>')

    ov_tab = (tldr_html
              + river_placeholder
              + hl_html
              + (f'<h2>Omschrijving van de makers</h2>{desc_html}' if desc_html else ''))

    ch_html = ''
    if an.get('chapters'):
        ch_items = []
        chs = an['chapters']
        for i, ch in enumerate(chs):
            start_s = ch.get('start_seconds', 0)
            end_s = (chs[i + 1]['start_seconds'] if i + 1 < len(chs) else ep.get('s', 0))
            dur_s = max(0, (end_s or 0) - start_s)
            dur_str = f'{round(dur_s / 60)} min' if dur_s else ''
            ts_btn = (f'<button class="tbtn" type="button" data-seek="{round(start_s)}">'
                      f'{ts_fmt(start_s)}</button>')
            ch_items.append(
                f'<li data-ch="{i}">'
                f'<div class="when">{ts_btn}<span>{dur_str}</span></div>'
                f'<div><h3>{esc(ch.get("title", ""))}</h3>'
                + (f'<p>{esc(ch.get("summary", ""))}</p>' if ch.get('summary') else '')
                + f'</div></li>')
        ch_html = f'<ol class="chapters">{"".join(ch_items)}</ol>'

    ch_placeholder = ('<p class="prose muted" style="padding:16px 0">Hoofdstukindeling beschikbaar '
                      'zodra de analyse van deze aflevering klaar is.</p>')

    tx_tab = (
        '<div class="trctrl">'
        '<input type="search" id="tr-q" placeholder="Zoek in dit gesprek" '
        'aria-label="Zoek in dit transcript">'
        '<label class="check"><input type="checkbox" id="tr-follow" checked> '
        'Volg de speler</label></div>'
        '<div class="segs" id="segs">'
        '<p class="loading" style="padding:16px 0 0">Transcript wordt geladen\u2026</p></div>'
    )

    tabs_html = (
        '<div class="tabs" role="tablist" aria-label="Inhoud">'
        '<button class="tab on" data-tab="ov" role="tab" aria-selected="true">Overzicht</button>'
        '<button class="tab" data-tab="ch" role="tab" aria-selected="false">Hoofdstukken</button>'
        '<button class="tab" data-tab="tr" role="tab" aria-selected="false">Transcript</button>'
        '<button class="tab" data-tab="an" role="tab" aria-selected="false">Analyse</button>'
        '</div>'
        f'<div class="txwrap">'
        f'<div class="tabp" data-p="ov">{ov_tab}</div>'
        f'<div class="tabp" data-p="ch" hidden>{ch_html or ch_placeholder}</div>'
        f'<div class="tabp" data-p="tr" hidden>{tx_tab}</div>'
        f'<div class="tabp" data-p="an" hidden><div data-analyse-pending></div></div>'
        f'</div>'
    )
    npo = npo_url(ep)
    mp3 = ep.get('mp3', '')
    listen_btn = ''
    if npo or mp3:
        listen_btn = (f'<button class="btn solid" id="luister-btn" type="button" '
                      f'data-npo="{esc(npo)}" data-mp3="{esc(mp3)}">Luister</button>')

    epno_label = f'Aflevering {n}' if n is not None else esc(fmt)
    if fmt != 'Gesprek' and n is not None:
        epno_label += f' · {fmt}'

    def prev_next_link(e, arrow):
        if not e:
            return ''
        t = e.get('t', '')
        t_short = t[:60] + ('…' if len(t) > 60 else '')
        n_part = f'#{e["n"]} ' if e.get('n') is not None else ''
        if arrow == 'left':
            return f'<a href="/aflevering/{ep_key(e)}/">← {n_part}{esc(t_short)}</a>'
        return f'<a href="/aflevering/{ep_key(e)}/">{n_part}{esc(t_short)} -></a>'

    left = (
        f'<div class="crumb"><a href="/afleveringen/">Afleveringen</a> / '
        f'{"#" + str(n) if n is not None else esc(fmt)}</div>'
        f'<div class="epno">{esc(epno_label)}</div>'
        f'<h1 style="margin:6px 0 10px">{esc(ep.get("t", ""))}</h1>'
        f'<div class="meta ui muted">'
        f'{esc(fmt_date(ep.get("d", "")))} · {fmt_dur(ep.get("s", 0))}</div>'
        f'<div class="actions" style="margin:12px 0">{listen_btn}</div>'
        f'{tabs_html}'
        + (f'<h2 style="margin:32px 0 6px">Door de makers aangeraden</h2>'
           f'<div class="eps">{"".join(ep_row_html(e) for e in rel_eps)}</div>'
           if rel_eps else '')
        + f'<h2 style="margin:32px 0 6px">Lijkt op deze aflevering</h2>'
        + ('' if sim_is_llm else
           '<p class="ui muted" style="font-size:14px;margin:0 0 8px">'
           'Op basis van overeenkomende woorden.</p>')
        + f'<div class="eps">{"".join(ep_row_html(e) for e in sim_eps)}</div>'
        + f'<div class="prevnext">'
        + prev_next_link(older, 'left')
        + (f'<span></span>' if not older else '')
        + prev_next_link(newer, 'right')
        + f'</div>')

    theme_chips = ''.join(
        f'<a class="chip" href="/thema/{slug(t)}/">{esc(t)}</a>'
        for t in ep.get('th', []))

    if ep.get('d'):
        try:
            import datetime as _dt2
            wd = _dt2.date.fromisoformat(ep['d']).isoweekday() % 7
            day_dd = f'<dt>Dag</dt><dd>{esc(DAYS_NL[wd])}</dd>'
        except Exception:
            day_dd = ''
    else:
        day_dd = ''

    right = (
        f'<div class="panel"><h3>Aan tafel</h3>'
        f'<div class="cast">{"".join(cast_card(c) for c in cast)}</div></div>'
        f'<div class="panel"><h3>Gegevens</h3><dl class="kv">'
        f'<dt>Nummer</dt><dd>{n if n is not None else "—"}</dd>'
        f'<dt>Datum</dt><dd>{esc(fmt_date(ep.get("d", "")))}</dd>'
        f'{day_dd}'
        f'<dt>Duur</dt><dd>{fmt_dur(ep.get("s", 0))}</dd>'
        f'<dt>Vorm</dt><dd>{esc(fmt)}</dd>'
        f'</dl></div>'
        + (f'<div class="panel"><h3>Thema\'s</h3>'
           f'<div class="chips" style="margin:0">{theme_chips}</div></div>'
           if theme_chips else '')
        + (lambda kws: f'<div class="panel"><h3>Sleutelwoorden</h3>'
           f'<p class="ui" style="font-size:14px;margin:0">'
           f'{", ".join(esc(w) for w in kws)}</p></div>'
           if kws else '')(an.get('keywords') or ep.get('kw') or [])
        + people_panel_html(an.get('people', []), data.people_dict)
        + book_panel_html(an.get('books', []))
        + bible_refs_html(an.get('bible_refs', []))
        + (f'<div class="panel"><h3>Wist je dat</h3><ul class="trivia">'
           f'{"".join(f"<li>{t}</li>" for t in trivia)}</ul></div>'
           if trivia else ''))

    # Pass player data via data-* on a hidden div (app.js reads these)
    meta_div = (f'<div id="ep-meta" hidden '
                f'data-ep-key="{esc(key)}" '
                f'data-ep-dur="{ep.get("s", 0)}" '
                f'data-mp3="{esc(mp3)}" '
                f'data-npo="{esc(npo)}"></div>')

    content = (f'{meta_div}'
               f'<div class="detail">'
               f'<article style="min-width:0">{left}</article>'
               f'<aside class="side">{right}</aside></div>')

    og_desc = (an.get('summary_tldr', '') or ep.get('xs', '') or ep.get('x', ''))[:160]
    write_page(out / 'aflevering' / key / 'index.html',
               ep.get('t', ''), content,
               nav_active='afleveringen', page_type='episode',
               og_meta={'description': og_desc},
               canonical=f'{_BASE_URL}/aflevering/{key}/')


# ============================================================
# SECTION 7: ASSET EXTRACTION AND COPYING
# ============================================================

def extract_css(template_path: pathlib.Path) -> str:
    """Extract the content between <style> and </style> in the template."""
    text = template_path.read_text(encoding='utf-8')
    m = re.search(r'<style[^>]*>(.*?)</style>', text, re.DOTALL)
    if not m:
        return ''
    css = m.group(1)
    # Remove template placeholder comments and rules not relevant to static site
    css = re.sub(r'/\*\s*__.*?__\s*\*/', '', css)
    return css


def write_assets(out: pathlib.Path, logo_src: pathlib.Path,
                 wordmark_src: pathlib.Path, template_path: pathlib.Path):
    """Write /assets/style.css and copy logo/wordmark."""
    assets = out / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    css = extract_css(template_path)
    # Append static-site specific rules
    css += '\n'
    css += '.hidden{display:none!important}\n'
    css += '.mention-row{display:flex;align-items:center;padding:7px 0;'
    css += 'border-bottom:1px solid var(--rule)}\n'
    css += '.mention-row a{color:inherit;text-decoration:none}\n'
    css += '.mention-row:last-child{border-bottom:none}\n'
    css += '.cast .person{margin-bottom:6px}\n'
    css += '.searchgrid{display:grid;grid-template-columns:220px 1fr;gap:24px;align-items:start}'
    css += '\n@media(max-width:700px){.searchgrid{grid-template-columns:1fr}}'
    css += '\n.bigq{width:100%;padding:8px 12px;border:1px solid var(--rule);'
    css += 'border-radius:10px;font-size:16px;background:var(--parchment-2);color:var(--ink)}'
    css += '\n.filters fieldset{border:none;padding:0;margin:0 0 16px}'
    css += '\n.filters select{width:100%;padding:5px 8px;border:1px solid var(--rule);'
    css += 'border-radius:4px;background:var(--parchment-2);color:var(--ink);font-size:14px}'
    css += '\n.prevnext{display:flex;justify-content:space-between;gap:12px;'
    css += 'margin:28px 0;font-size:14px;border-top:1px solid var(--rule);padding-top:16px}'
    css += '\n.prevnext a{color:var(--violet);text-decoration:none;'
    css += 'max-width:48%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}'
    css += '\n.tabp[hidden]{display:none}\n'
    css += '.tabs{display:flex;gap:2px;align-items:center;border-bottom:1px solid var(--ink);'
    css += 'margin-bottom:22px;overflow-x:auto;scrollbar-width:none}'
    css += '\n.tab{font:600 15px/1 var(--ui);white-space:nowrap;padding:12px 12px;border:0;'
    css += 'background:none;color:var(--ink-muted);cursor:pointer;'
    css += 'border-bottom:3px solid transparent;margin-bottom:-2px}'
    css += '\n.tab:hover{color:var(--ink)}'
    css += '\n.tab.on{color:var(--ink);border-bottom-color:var(--violet)}'
    css += '\n.txwrap{margin-top:8px}'
    css += '\n.hl{list-style:none;padding:0;margin:0}'
    css += '\n.hl li{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--rule)}'
    css += '\n.hl li:last-child{border-bottom:none}'
    css += '\n.tbtn{font:600 13px/1 var(--ui);font-variant-numeric:tabular-nums;color:var(--violet);'
    css += 'background:transparent;border:1px solid var(--rule);border-radius:999px;'
    css += 'padding:6px 9px;cursor:pointer;white-space:nowrap}'
    css += '\n.chapters{list-style:none;padding:0;margin:0}'
    css += '\n.chapters li{display:flex;gap:16px;padding:12px 0;'
    css += 'border-bottom:1px solid var(--rule)}'
    css += '\n.chapters .when{display:flex;flex-direction:column;gap:4px;'
    css += 'align-items:flex-start;min-width:60px}'
    css += '\n.trivia{padding-left:18px;margin:0}'
    css += '\n.trivia li{margin-bottom:6px;font-size:15px}'
    css += '\nbr+br{display:none}'
    css += '\ntable.tics{border-collapse:collapse;font:14px var(--ui);width:100%}'
    css += '\ntable.tics th,table.tics td{padding:7px 8px;border-bottom:1px solid var(--rule);text-align:right;font-variant-numeric:tabular-nums}'
    css += '\ntable.tics th:first-child,table.tics td:first-child{text-align:left}'
    css += '\ntable.tics thead th{font-weight:600;color:var(--ink-muted);font-size:12.5px}'
    css += '\ntable.tics td.hot{color:var(--ink);font-weight:700}'
    css += '\n.anchart{width:100%;max-width:720px;display:block;margin:12px 0}'
    css += '\n.anchart .grid{stroke:var(--rule);stroke-width:1}'
    css += '\n.anchart .line{fill:none;stroke:var(--gold);stroke-width:2}'
    css += '\n.anchart text{font:12px var(--ui);fill:var(--ink-muted)}'
    (assets / 'style.css').write_text(css, encoding='utf-8')
    if logo_src.exists():
        shutil.copy2(logo_src, assets / 'logo.jpg')
    if wordmark_src.exists():
        shutil.copy2(wordmark_src, assets / 'wordmark.png')
    print(f'  assets: style.css, logo.jpg, wordmark.png -> {assets}')


def copy_data_files(dist_data: pathlib.Path, out: pathlib.Path,
                    root: pathlib.Path):
    """Copy transcripts, word_index, person images, and bvdata.json to static output."""
    out_data = out / 'data'
    out_data.mkdir(parents=True, exist_ok=True)

    # Transcripts
    tx_src = dist_data / 'transcripts'
    tx_dst = out_data / 'transcripts'
    if tx_src.exists():
        tx_dst.mkdir(parents=True, exist_ok=True)
        n = sum(1 for f in tx_src.glob('*.json')
                if shutil.copy2(f, tx_dst / f.name) is None or True)
        print(f'  transcripts: {n} files -> {tx_dst}')

    # Word index
    wi = dist_data / 'word_index.json'
    if wi.exists():
        shutil.copy2(wi, out_data / 'word_index.json')
        print(f'  word_index.json ({wi.stat().st_size // 1024} KB) -> {out_data}')

    # Person images
    img_src = root / 'data' / 'persons' / 'images'
    img_dst = out_data / 'persons' / 'images'
    if img_src.exists():
        img_dst.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in img_src.iterdir():
            if f.suffix.lower() in ('.jpg', '.jpeg', '.jfif', '.png', '.webp'):
                dst_name = f.stem + '.jpg' if f.suffix.lower() == '.jfif' else f.name
                shutil.copy2(f, img_dst / dst_name)
                n += 1
        print(f'  person images: {n} -> {img_dst}')

    # Build bvdata.json (Bible verses) — same logic as 5_build_site.py
    global _BVDATA
    bvdata = _build_bvdata(root)
    _BVDATA = bvdata
    (out_data / 'bvdata.json').write_text(
        json.dumps(bvdata, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8')
    print(f'  bvdata.json: {len(bvdata)} verse entries -> {out_data}')


def _build_bvdata(root: pathlib.Path) -> dict:
    """Collect Bible verse data from analysis/*.json and bible/*.json."""
    bible_dir = root / 'data' / 'bible'
    analysis_dir = root / 'data' / 'analysis'
    if not bible_dir.exists():
        return {}

    book_cache = {}

    def get_book(code):
        if code not in book_cache:
            f = bible_dir / f'{code}.json'
            book_cache[code] = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
        return book_cache[code]

    def verses_for(code, ch, v):
        ch_data = get_book(code).get(str(ch), {})
        return [ch_data[str(v + i)] for i in range(3) if str(v + i) in ch_data]

    # Reuse DUTCH_TO_OSIS mapping defined earlier in this file
    REF_RE = re.compile(
        r'^(?P<book>(?:\d\s+)?[A-Za-zÀ-ɏ]+(?:\s+[A-Za-zÀ-ɏ]+)*)'
        r'\s+(?P<ch>\d+)(?::(?P<v>\d+)(?:-\d+)?)?')

    def parse_ref(ref):
        ref = ref.strip()
        ref = re.sub(r'\s*\(.*\)', '', ref).strip()
        ref = re.sub(r'(\d+)-\d+', r'\1', ref)
        m = REF_RE.match(ref)
        if not m:
            return None
        book_raw = m.group('book').strip().lower()
        ch = int(m.group('ch'))
        v = int(m.group('v')) if m.group('v') else 1
        code = DUTCH_TO_OSIS.get(book_raw)
        if not code:
            return None
        return code, ch, v

    all_refs = set()
    if analysis_dir.exists():
        for f in analysis_dir.glob('*.json'):
            try:
                for b in json.loads(f.read_text(encoding='utf-8')).get('bible_refs', []):
                    if b.get('ref'):
                        all_refs.add(b['ref'])
            except Exception:
                pass

    bv = {}
    for ref in sorted(all_refs):
        parsed = parse_ref(ref)
        if not parsed:
            continue
        code, ch, v = parsed
        key = f'{code}.{ch}.{v}'
        if key not in bv:
            texts = verses_for(code, ch, v)
            if texts:
                bv[key] = texts
    return bv


# ============================================================
# SECTION 8: SITEMAP AND ROBOTS
# ============================================================

def write_sitemap(urls: list, out: pathlib.Path, base_url: str):
    """Write XML sitemap."""
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url, lastmod in urls:
        lines.append(f'  <url><loc>{esc(base_url.rstrip("/"))}{url}</loc>'
                     + (f'<lastmod>{lastmod}</lastmod>' if lastmod else '')
                     + '</url>')
    lines.append('</urlset>')
    (out / 'sitemap.xml').write_text('\n'.join(lines), encoding='utf-8')
    print(f'  sitemap.xml: {len(urls)} URLs')


def write_robots(out: pathlib.Path, base_url: str):
    (out / 'robots.txt').write_text(
        f'User-agent: *\nAllow: /\nSitemap: {base_url.rstrip("/")}/sitemap.xml\n',
        encoding='utf-8')
    print('  robots.txt written')


# ============================================================
# SECTION 9: MAIN
# ============================================================

def main():
    global _BUILT_DATE, _BASE_URL, _COVER_URLS

    import argparse
    parser = argparse.ArgumentParser(description='Build static multi-page site')
    parser.add_argument('--output-dir', default=str(ROOT / 'site' / 'static'),
                        help='Output directory (default: site/static)')
    parser.add_argument('--base-url', default='https://www.deongelooflijkearchief.nl',
                        help='Canonical base URL (no trailing slash)')
    parser.add_argument('--clean', action='store_true',
                        help='Delete output directory before building')
    parser.add_argument('--offline', action='store_true',
                        help='Use cached book covers without downloading missing images')
    parser.add_argument('--retry-missing-covers', action='store_true',
                        help='Retry unavailable covers immediately instead of waiting 24 hours')
    args = parser.parse_args()

    out = pathlib.Path(args.output_dir)
    _BASE_URL = args.base_url.rstrip('/')

    if args.clean and out.exists():
        shutil.rmtree(out)
        print(f'Cleaned {out}')

    out.mkdir(parents=True, exist_ok=True)
    print("Building static site -> " + str(out))
    _COVER_URLS = prepare_covers(ROOT, out, offline=args.offline,
                                retry_missing=args.retry_missing_covers)

    # Locate source assets
    logo_src = ROOT / 'design-system' / 'assets' / 'logos' / 'logo360.jpg'
    wordmark_src = ROOT / 'design-system' / 'assets' / 'logos' / 'wordmark672.png'
    template_path = ROOT / 'site' / 'src' / 'index.template.html'
    dist_data = ROOT / 'site' / 'dist' / 'data'
    app_js_src = ROOT / 'site' / 'src' / 'app.js'

    _BUILT_DATE = _date.today().isoformat()

    # Write CSS/logo assets
    write_assets(out, logo_src, wordmark_src, template_path)

    # Copy app.js (must exist at site/src/app.js)
    if app_js_src.exists():
        shutil.copy2(app_js_src, out / 'assets' / 'app.js')
        print(f'  app.js -> {out / "assets" / "app.js"}')
    else:
        (out / 'assets' / 'app.js').write_text('/* app.js placeholder */', encoding='utf-8')
        print('  app.js: placeholder (create site/src/app.js for full interactivity)')

    # Copy data files
    copy_data_files(dist_data, out, ROOT)

    # Load all data
    print('Loading site data...')
    data = load_data(dist_data)
    _BUILT_DATE = data.built or _BUILT_DATE

    # Build all pages
    print(f'Building {len(data.all_eps)} episode pages...')
    urls = []
    today = _BUILT_DATE

    build_home(data, out)
    urls.append(('/', today))

    build_episode_list(data, out)
    urls.append(('/afleveringen/', today))

    build_guest_list(data, out)
    urls.append(('/gasten/', today))

    for g in data.guests.values():
        build_guest_detail(data, g, out)
        urls.append((f'/gast/{g["k"]}/', today))
    print(f'  {len(data.guests)} guest pages')

    build_persons_list(data, out)
    urls.append(('/personen/', today))

    if isinstance(data.people_dict, dict):
        for p_slug in data.people_dict:
            build_person_detail(data, p_slug, out)
            urls.append((f'/persoon/{p_slug}/', today))
        print(f'  {len(data.people_dict)} person pages')

    build_books_list(data, out)
    urls.append(('/boeken/', today))

    for book in data.books_list:
        bkey = book.get('book_key', '') or book.get('isbn13', '') or slug(book.get('n', ''))
        if bkey:
            build_book_detail(data, book, out)
            urls.append((f'/boek/{bkey}/', today))
    print(f'  {len(data.books_list)} book pages')

    build_themes_list(data, out)
    urls.append(('/themas/', today))

    for theme in data.themes:
        build_theme_detail(data, theme, out)
        urls.append((f'/thema/{slug(theme)}/', today))
    print(f'  {len(data.themes)} theme pages')

    build_stats(data, out)
    urls.append(('/statistieken/', today))

    for ep in data.all_eps:
        build_episode_detail(data, ep, out)
        key = ep_key(ep)
        urls.append((f'/aflevering/{key}/', ep.get('d', today)))

    print(f'  {len(data.all_eps)} episode pages')

    write_sitemap(urls, out, _BASE_URL)
    write_robots(out, _BASE_URL)

    total = sum(1 for _ in out.rglob('*.html'))
    print(f'\nDone: {total} HTML pages, sitemap.xml, robots.txt -> {out}')


if __name__ == '__main__':
    main()
