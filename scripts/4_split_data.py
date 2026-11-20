"""Split episodes.json into per-episode files and build aggregate data files.

Outputs:
  site/dist/data/episodes/{key}.json   — all fields + pre-computed kw
  site/dist/data/index.json            — episode keys list (for --all-missing flag)
  site/dist/data/speakers.json         — aggregated speaker stats ([] if no transcripts)
  site/dist/data/books.json            — book mention aggregates ([] if no transcripts)
  site/dist/data/places.json           — place mention aggregates ([] if no transcripts)
  site/dist/data/people.json           — person mention aggregates ([] if no transcripts)
"""
import json, math, pathlib, re, unicodedata
from utils import ep_key, truncate_xs

ROOT = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON = ROOT / 'data' / 'episodes.json'
TRANSCRIPTS_DIR = ROOT / 'data' / 'transcripts'
ANALYSIS_DIR = ROOT / 'data' / 'analysis'
BOOKS_DIR = ROOT / 'data' / 'books'
OUT_DIR = ROOT / 'site' / 'dist' / 'data'

# Fields from analysis to include in per-episode site files
_AN_FIELDS = {'summary_tldr', 'summary_points', 'chapters', 'highlights',
              'bible_refs', 'themes', 'guests', 'people', 'books', 'places', 'quotes', 'keywords',
              'similar'}

# ---------------------------------------------------------------------------
# Stop words — exact copy of the STOP set from index.template.html
# ---------------------------------------------------------------------------
STOP = set("""aan aangezien achter af al alle allemaal alleen alles als altijd
ander andere anders behalve beide ben bent beter bij binnen boven bovendien
daar daarbij daarin daarna daarom daarover dan dat de deze die dit doch doen
door dus echter een eens eerst eerste elk elke en enige enkele enz er erg
ergens even ga gaan gaat geen gehad geweest gewoon haar had heb hebben heeft
hem het hier hij hoe hoewel hun ik in is ja je jij jou jouw juist kan kon
konden kun kunnen maar me meer meeste men met mij mijn misschien moet moeten
na naar nadat net niet niets nog nooit nu of om omdat onder ons onze ook op
over pas per plaats reeds rond samen sinds sommige steeds te tegen ten ter
tijdens toch toe toen tot tussen u uit uw van vanaf veel verder via vol voor
vooral vrij waar waarom wanneer want waren was wat we wel welk welke werd
werden wie wij wil willen word worden wordt zal ze zelf zich zichzelf zij
zijn zo zoals zodat zonder zou zouden zulke bijvoorbeeld eigenlijk echt heel
weer gaat komt komen kwam maakt maken laat laten staat staan zegt zeggen zien
ziet waarin waarmee waardoor iets iemand jaar jaren keer onze deze dezen hele
zeer best goed groot grote kleine klein nieuwe nieuw oude lang lange veel
vele weinig andere eigen manier vraag vragen vraagt waarbij hierover welke
zowel zult wellicht vaak soms tweede twee drie vier vijf zes zeven acht negen
tien honderd duizend daarnaast zelfs bijna helemaal tegelijkertijd terwijl
totdat volgens tijdens binnenkort inmiddels ondanks verschillende eerder later
vandaag gisteren morgen uiteraard natuurlijk volgens ervan erover ermee erin
hierin waarover hebt had heeft zitten zit kunnen krijgen krijgt gaan ging
gingen gaat moet mogen mag spreekt spreken sprak praat praten gesprek
gesprekken aflevering afleveringen podcast ongelooflijke david boogerd stefan
paas vaste gast gasten theoloog hoogleraar universiteit spreekt bespreken
bespreekt bespreekt vertelt vertellen waarover samen luister luisteren deel
nieuwste vorige volgende waarom hoe wat wie welke anno ging zien doet deed
gedaan leven mensen mens dingen ding wereld vindt vinden vond denk denkt
dacht nederland nederlandse amsterdam utrecht theologische vrije""".split())

_ACCENT_RE = re.compile(r'[̀-ͯ]')
_TOK_RE = re.compile(r'[a-zà-öø-ÿ]+(?:-[a-zà-öø-ÿ]+)*')


def norm(s):
    return _ACCENT_RE.sub('', unicodedata.normalize('NFD', s.lower()))


def tok(s):
    return [w for w in _TOK_RE.findall(norm(s)) if len(w) > 3 and w not in STOP]


def compute_tfidf(eps):
    """Add tf, vec, kw to each episode dict. Modifies in place."""
    df = {}
    for e in eps:
        tokens = tok(e['t'] + ' ' + e['t'] + ' ' + e.get('x', ''))
        tf = {}
        for w in tokens:
            tf[w] = tf.get(w, 0) + 1
        e['_tf'] = tf
        for w in tf:
            df[w] = df.get(w, 0) + 1

    n = len(eps)
    for e in eps:
        tf = e['_tf']
        v = {}
        norm_sq = 0.0
        for w, cnt in tf.items():
            x = cnt * math.log(n / df[w])
            v[w] = x
            norm_sq += x * x
        length = math.sqrt(norm_sq) or 1.0
        for w in v:
            v[w] /= length
        # top-10 keywords: at least 2 docs have this word (matches JS filter DF[w]>1)
        kw = sorted(
            ((w, s) for w, s in v.items() if df[w] > 1),
            key=lambda x: x[1], reverse=True
        )[:10]
        e['_kw'] = [w for w, _ in kw]
        del e['_tf']


# ---------------------------------------------------------------------------
# Aggregate helpers (used when transcripts exist)
# ---------------------------------------------------------------------------

def build_mention_aggregate(transcripts, eps_by_key):
    """Build people/books/places aggregates from transcript mention lists.
    Stores speaker names (not IDs) and per-episode hit timestamps.
    """
    by_name = {}
    for tr in transcripts:
        ep_key_val = str(tr.get('episode'))
        ep = eps_by_key.get(ep_key_val)
        if not ep:
            continue
        yr = ep['d'][:4]
        ep_info = {'n': ep['n'], 't': ep['t'], 'd': ep['d']}

        # Build speaker ID -> name map for this transcript
        spk_names = {s['id']: s['name'] for s in tr.get('speakers', [])}

        # Group mentions by normalised name within this episode
        ep_ment = {}
        for m in tr.get('mentions', []):
            name = m.get('name', '')
            if not name:
                continue
            typ = m.get('type', 'persoon')
            sp_name = spk_names.get(m.get('speaker', ''), '')
            t = m.get('t', -1)
            nkey = norm(name)
            if nkey not in ep_ment:
                ep_ment[nkey] = {'name': name, 'c': typ, 'x': 0, 'hits': []}
            ep_ment[nkey]['x'] += 1
            if t >= 0:
                ep_ment[nkey]['hits'].append({'t': round(float(t), 1), 'sp': sp_name})

        for nkey, em in ep_ment.items():
            if nkey not in by_name:
                by_name[nkey] = {'n': em['name'], 'c': em['c'], 'k': nkey,
                                 'x': 0, 'eps': [], 'sp': {}, 'yr': {}}
            entry = by_name[nkey]
            entry['x'] += em['x']
            entry['yr'][yr] = entry['yr'].get(yr, 0) + em['x']
            ep_e = dict(ep_info, x=em['x'],
                        hits=sorted(em['hits'], key=lambda h: h['t']))
            entry['eps'].append(ep_e)
            for h in em['hits']:
                if h['sp']:
                    entry['sp'][h['sp']] = entry['sp'].get(h['sp'], 0) + 1

    for entry in by_name.values():
        entry['eps'].sort(key=lambda e: e['d'])
    return sorted(by_name.values(), key=lambda x: x['x'], reverse=True)


def _shift_start_seconds(an: dict, delta: int = -5) -> None:
    """Shift start_seconds on all timed analysis fields by delta seconds (min 0)."""
    for field in ('people', 'books', 'chapters', 'highlights'):
        for item in an.get(field) or []:
            if isinstance(item, dict) and item.get('start_seconds') is not None:
                item['start_seconds'] = max(0, item['start_seconds'] + delta)


def build_mention_aggregate_from_analysis(an_by_key, eps_by_key):
    """Build aggregate from analysis people/books/places (no timestamp or speaker data)."""
    by_name = {}
    for key, an in an_by_key.items():
        ep = eps_by_key.get(key)
        if not ep:
            continue
        yr = ep['d'][:4]
        ep_info = {'n': ep['n'], 't': ep['t'], 'd': ep['d']}

        for p in an.get('people', []):
            name = p.get('name', '') if isinstance(p, dict) else str(p)
            if not name:
                continue
            nkey = norm(name)
            if nkey not in by_name:
                by_name[nkey] = {'n': name, 'c': 'persoon', 'k': nkey,
                                 'x': 0, 'eps': [], 'sp': {}, 'yr': {}}
            entry = by_name[nkey]
            entry['x'] += 1
            entry['yr'][yr] = entry['yr'].get(yr, 0) + 1
            entry['eps'].append(dict(ep_info, x=1, hits=[]))
            # Carry wiki image from first occurrence that has one
            if not entry.get('img') and isinstance(p, dict) and p.get('wiki_pageid') and p.get('wiki_image'):
                entry['img'] = p['wiki_image']
                if p.get('wiki_url'):
                    entry['wiki_url'] = p['wiki_url']

        for b in an.get('books', []):
            name = b.get('canonical_title') or b.get('title', '')
            if not name:
                continue
            nkey = norm(name)
            t = b.get('start_seconds')
            hits = [{'t': float(t), 'sp': ''}] if t is not None and t >= 0 else []
            isbn13 = (b.get('isbn13') or '').strip()
            volume_id = (b.get('volume_id') or '').strip()
            book_key = isbn13 if isbn13 else (f'vol-{volume_id}' if volume_id else '')
            if nkey not in by_name:
                by_name[nkey] = {'n': name, 'c': 'boek', 'k': nkey,
                                 'x': 0, 'eps': [], 'sp': {}, 'yr': {}}
            entry = by_name[nkey]
            if book_key and not entry.get('book_key'):
                entry['book_key'] = book_key
            # Carry thumbnail from first occurrence that has one
            if not entry.get('bk_thumb') and (b.get('thumbnail') or '').strip():
                entry['bk_thumb'] = b['thumbnail'].replace('http:', 'https:')
            # Carry author from first occurrence that has one
            if not entry.get('author'):
                a_val = (b.get('canonical_author') or b.get('author') or '').strip()
                if a_val:
                    entry['author'] = a_val
            # Also carry the note per episode hit
            ep_note = b.get('note', '')
            entry['x'] += 1
            entry['yr'][yr] = entry['yr'].get(yr, 0) + 1
            ep_entry = dict(ep_info, x=1, hits=hits)
            if ep_note:
                ep_entry['note'] = ep_note
            entry['eps'].append(ep_entry)

        for p in an.get('places', []):
            name = p if isinstance(p, str) else p.get('name', '')
            if not name:
                continue
            nkey = norm(name)
            if nkey not in by_name:
                by_name[nkey] = {'n': name, 'c': 'plaats', 'k': nkey,
                                 'x': 0, 'eps': [], 'sp': {}, 'yr': {}}
            entry = by_name[nkey]
            entry['x'] += 1
            entry['yr'][yr] = entry['yr'].get(yr, 0) + 1
            entry['eps'].append(dict(ep_info, x=1, hits=[]))

    for entry in by_name.values():
        entry['eps'].sort(key=lambda e: e['d'])
    return sorted(by_name.values(), key=lambda x: x['x'], reverse=True)


def merge_mention_aggregates(primary, secondary):
    """Merge secondary into primary, deduplicating by entity key and episode number."""
    merged = {e['k']: e for e in primary}
    for entry in secondary:
        k = entry['k']
        if k in merged:
            existing_ns = {ep['n'] for ep in merged[k]['eps']}
            new_eps = [ep for ep in entry['eps'] if ep['n'] not in existing_ns]
            if new_eps:
                merged[k]['eps'].extend(new_eps)
                merged[k]['eps'].sort(key=lambda e: e['d'])
            for yr, cnt in entry['yr'].items():
                merged[k]['yr'][yr] = merged[k]['yr'].get(yr, 0) + cnt
            merged[k]['x'] += sum(ep['x'] for ep in new_eps)
            if not merged[k].get('img') and entry.get('img'):
                merged[k]['img'] = entry['img']
            if not merged[k].get('wiki_url') and entry.get('wiki_url'):
                merged[k]['wiki_url'] = entry['wiki_url']
        else:
            merged[k] = entry
    return sorted(merged.values(), key=lambda x: x['x'], reverse=True)


def build_speaker_aggregate(transcripts, eps_by_key):
    """Build per-speaker aggregate stats from all transcripts."""
    by_name = {}
    for tr in transcripts:
        ep_key_val = str(tr.get('episode'))
        ep = eps_by_key.get(ep_key_val, {})
        dur = ep.get('s', 0)
        spk_map = {s['id']: s for s in tr.get('speakers', [])}
        for s in tr.get('speakers', []):
            name = s['name']
            role = s.get('role', 'gast')
            if name not in by_name:
                by_name[name] = {'name': name, 'role': role,
                                 'eps': 0, 'time': 0.0, 'words': 0, 'turns': 0,
                                 'laughs': 0}
            agg = by_name[name]
            agg['eps'] += 1
            sid = s['id']
            # sum segment time and words for this speaker
            for seg in tr.get('segments', []):
                if seg.get('speaker') == sid:
                    agg['time'] += seg['end'] - seg['start']
                    agg['words'] += len(seg.get('text', '').split())
                    agg['turns'] += 1
            # count laughs
            for ev in tr.get('events', []):
                if ev.get('type') == 'laugh' and ev.get('speaker') == sid:
                    agg['laughs'] += 1

    # compute derived fields
    result = []
    for name, agg in by_name.items():
        minutes = agg['time'] / 60.0
        agg['wpm'] = round(agg['words'] / minutes) if minutes > 0 else 0
        result.append(agg)
    return sorted(result, key=lambda x: x['time'], reverse=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    data = json.loads(EPISODES_JSON.read_text(encoding='utf-8'))
    eps = data['eps']

    # Compute TF-IDF keywords for all episodes
    compute_tfidf(eps)

    # Output directories
    ep_dir = OUT_DIR / 'episodes'
    ep_dir.mkdir(parents=True, exist_ok=True)

    # Build lookup for aggregates
    eps_by_key = {ep_key(e): e for e in eps}

    # Load analysis files (keyed by episode number string)
    an_by_key = {}
    if ANALYSIS_DIR.exists():
        for f in ANALYSIS_DIR.glob('*.json'):
            try:
                an = json.loads(f.read_text(encoding='utf-8'))
                an = {k: v for k, v in an.items() if k in _AN_FIELDS}
                _shift_start_seconds(an, delta=-5)
                an_by_key[f.stem] = an
            except Exception as exc:
                print(f'  Warning: could not read analysis/{f.name}: {exc}')

    # Write per-episode files (all fields + kw + optional analysis)
    keys = []
    n_analysis = 0
    for e in eps:
        key = ep_key(e)
        keys.append(key)
        entry = {k: v for k, v in e.items() if not k.startswith('_')}
        entry['kw'] = e['_kw']
        an = an_by_key.get(key)
        if an:
            entry['an'] = an
            n_analysis += 1
            # Overlay LLM-extracted guests and themes onto the base episode fields
            if an.get('guests'):
                entry['g'] = an['guests']
            if an.get('themes'):
                entry['th'] = an['themes']
        path = ep_dir / f'{key}.json'
        path.write_text(json.dumps(entry, ensure_ascii=False, separators=(',', ':')),
                        encoding='utf-8')

    # Write index.json (episode keys list for --all-missing transcription)
    (OUT_DIR / 'index.json').write_text(
        json.dumps(keys, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8'
    )

    # Build aggregates from transcripts if they exist
    transcripts = []
    if TRANSCRIPTS_DIR.exists():
        for f in sorted(TRANSCRIPTS_DIR.glob('*.json')):
            try:
                tr = json.loads(f.read_text(encoding='utf-8'))
                transcripts.append(tr)
            except Exception as exc:
                print(f'  Warning: could not read {f.name}: {exc}')

    if transcripts:
        tx_mentions = build_mention_aggregate(transcripts, eps_by_key)
        speakers = build_speaker_aggregate(transcripts, eps_by_key)
    else:
        tx_mentions = []
        speakers = []

    an_mentions = build_mention_aggregate_from_analysis(an_by_key, eps_by_key)
    mention_all = merge_mention_aggregates(tx_mentions, an_mentions)

    books   = [m for m in mention_all if m['c'] == 'boek']
    places  = [m for m in mention_all if m['c'] == 'plaats']
    people  = [m for m in mention_all if m['c'] in ('persoon', 'filosoof')]

    for name, obj in [('speakers', speakers), ('books', books),
                      ('places', places), ('people', people)]:
        (OUT_DIR / f'{name}.json').write_text(
            json.dumps(obj, ensure_ascii=False, separators=(',', ':')),
            encoding='utf-8'
        )

    # Copy per-book detail files from data/books/ to site/dist/data/books/
    n_books_copied = 0
    if BOOKS_DIR.exists():
        books_out = OUT_DIR / 'books'
        books_out.mkdir(parents=True, exist_ok=True)
        for src in BOOKS_DIR.glob('*.json'):
            dst = books_out / src.name
            dst.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
            n_books_copied += 1

    total = len(list(ep_dir.iterdir()))
    print(f'site/dist/data/: {total} episode files, '
          f'{len(transcripts)} transcripts aggregated, '
          f'{n_analysis} with analysis, '
          f'{n_books_copied} book detail files')


if __name__ == '__main__':
    main()
