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

ROOT = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON = ROOT / 'data' / 'episodes.json'
TRANSCRIPTS_DIR = ROOT / 'data' / 'transcripts'
OUT_DIR = ROOT / 'site' / 'dist' / 'data'

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


def ep_key(e):
    return str(e['n']) if e['n'] is not None else 'x' + e['id']


def truncate_xs(text, max_chars=320):
    """Truncate at word boundary, no mid-word cuts."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(None, 1)[0]
    return cut if cut else text[:max_chars]


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
    """Build people/books/places aggregates from transcript mention lists."""
    by_name = {}
    for tr in transcripts:
        ep_key_val = str(tr.get('episode'))
        ep = eps_by_key.get(ep_key_val)
        ep_info = {'n': ep['n'], 't': ep['t'], 'd': ep['d']} if ep else {'n': None, 't': '', 'd': ''}
        for m in tr.get('mentions', []):
            name = m['name']
            typ = m['type']
            key = norm(name)
            if key not in by_name:
                by_name[key] = {'n': name, 'c': typ, 'k': key, 'x': 0,
                                'eps': [], 'sp': {}, 'yr': {}}
            entry = by_name[key]
            entry['x'] += 1
            yr = str(ep['d'][:4]) if ep else '?'
            entry['yr'][yr] = entry['yr'].get(yr, 0) + 1
            spk = m.get('speaker', '')
            if spk:
                entry['sp'][spk] = entry['sp'].get(spk, 0) + 1
            # add ep_info once per episode
            if not any(e['n'] == ep_info['n'] and e['d'] == ep_info['d']
                       for e in entry['eps']):
                entry['eps'].append(ep_info)
    return sorted(by_name.values(), key=lambda x: x['x'], reverse=True)


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
            role = s['role']
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

    # Write per-episode files (all fields + kw)
    keys = []
    for e in eps:
        key = ep_key(e)
        keys.append(key)
        entry = {k: v for k, v in e.items() if not k.startswith('_')}
        entry['kw'] = e['_kw']
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
                transcripts.append(json.loads(f.read_text(encoding='utf-8')))
            except Exception as exc:
                print(f'  Warning: could not read {f.name}: {exc}')

    if transcripts:
        mention_all = build_mention_aggregate(transcripts, eps_by_key)
        books   = [m for m in mention_all if m['c'] == 'boek']
        places  = [m for m in mention_all if m['c'] == 'plaats']
        people  = [m for m in mention_all if m['c'] in ('persoon', 'filosoof')]
        speakers = build_speaker_aggregate(transcripts, eps_by_key)
    else:
        books = places = people = speakers = []

    for name, obj in [('speakers', speakers), ('books', books),
                      ('places', places), ('people', people)]:
        (OUT_DIR / f'{name}.json').write_text(
            json.dumps(obj, ensure_ascii=False, separators=(',', ':')),
            encoding='utf-8'
        )

    total = len(list(ep_dir.iterdir()))
    print(f'site/dist/data/: {total} episode files, '
          f'{len(transcripts)} transcripts aggregated')


if __name__ == '__main__':
    main()
