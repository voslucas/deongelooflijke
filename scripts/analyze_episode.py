"""Analyse a transcribed podcast episode with Claude and write data/analysis/{n}.json.

Usage:
    python scripts/analyze_episode.py --episode 327
    python scripts/analyze_episode.py --all-missing          # all episodes with transcript but no analysis
    python scripts/analyze_episode.py --all-missing --force  # re-analyse everything
    python scripts/analyze_episode.py --episode 327 --model claude-sonnet-5-5

Reads:
    data/feed/{n}.json          feed snapshot (title, description, guests, date)
    data/transcripts/{n}.json   transcript (segments with speaker names)
    data/themes.json            fixed theme list

Writes:
    data/analysis/{n}.json      LLM-extracted fields

Requires:
    pip install anthropic
    ANTHROPIC_API_KEY env var (or ant auth login profile)
    GOOGLE_BOOKS_API_KEY env var (optional; improves rate limits for book enrichment)
"""
import argparse, json, os, re, sys, time, datetime, urllib.request, urllib.parse, urllib.error
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR_FEED      = ROOT / 'data' / 'feed'
DIR_TR        = ROOT / 'data' / 'transcripts'
DIR_OUT       = ROOT / 'data' / 'analysis'
THEMES_PATH   = ROOT / 'data' / 'themes.json'
EPISODES_JSON = ROOT / 'data' / 'episodes.json'

DEFAULT_MODEL = 'claude-sonnet-5-5'
MAX_TRANSCRIPT_CHARS = 60_000  # stay comfortably within context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_feed(key: str) -> dict | None:
    p = DIR_FEED / f'{key}.json'
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding='utf-8'))


def _load_transcript(key: str) -> dict | None:
    p = DIR_TR / f'{key}.json'
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding='utf-8'))


def _transcript_text(tr: dict) -> str:
    """Convert transcript segments to timestamped plain text for the LLM."""
    speaker_map = {}
    for sp in tr.get('speakers', []):
        speaker_map[sp['id']] = sp['name']

    lines = []
    for seg in tr.get('segments', []):
        name = speaker_map.get(seg.get('speaker', ''), seg.get('speaker', '?'))
        text = seg.get('text', '').strip()
        if not text:
            continue
        start_s = seg.get('start', 0)
        mm, ss = divmod(int(start_s), 60)
        lines.append(f'[{mm:02d}:{ss:02d}] {name}: {text}')

    full = '\n'.join(lines)
    if len(full) > MAX_TRANSCRIPT_CHARS:
        full = full[:MAX_TRANSCRIPT_CHARS] + '\n[... transcript ingekort ...]'
    return full


def _build_system_prompt(themes: list[dict]) -> str:
    theme_labels = '\n'.join(f'  - {t["label"]} ({t["hint"]})' for t in themes)
    return f"""Je analyseert afleveringen van de Nederlandse podcast 'De Ongelooflijke Podcast'. \
Presentator is altijd David Boogerd. Vaste gast is theoloog Stefan Paas (aanwezig in de meeste afleveringen). \
Gasten zijn andere sprekers. Het transcript heeft tijdstempels in [MM:SS]-formaat voor elk segment.

Extraheer de volgende velden en geef je antwoord als ALLEEN valide JSON — geen markdown-omhulsel, geen uitleg:

{{
  "themes": [ "Thema 1", "Thema 2" ],
  "guests": [ "Volledige Naam" ],
  "people": [ {{"name": "Volledige Naam", "note": "korte rol of beschrijving", "start_seconds": 0}} ],
  "books": [ {{"title": "Boektitel", "author": "Auteur of leeg", "note": "optioneel", "start_seconds": 0}} ],
  "bible_refs": [ {{"ref": "Boek Hoofdstuk:Vers", "note": "context"}} ],
  "places": [ "Plaatsnaam" ],
  "summary_tldr": "2-3 zinnen die de kern van het gesprek beschrijven.",
  "summary_points": [ "Kernpunt 1", "Kernpunt 2" ],
  "chapters": [
    {{"start_seconds": 0, "title": "Hoofdstuktitel", "summary": "Korte beschrijving van dit deel."}}
  ],
  "highlights": [
    {{"start_seconds": 0, "speaker": "Naam", "text": "Treffende uitspraak of moment.", "note": "Waarom dit opvalt."}}
  ],
  "keywords": [ "sleutelwoord" ],
  "quotes": [ "citaat" ]
}}

REGELS:
- themes: kies maximaal 4 uit deze vaste lijst (kopieer het label exact):
{theme_labels}
- guests: directe gesprekspartners, NIET David Boogerd en NIET Stefan Paas.
- people: personen die besproken worden (ook historische figuren, politici, filosofen). \
  Normaliseer namen consistent (bijv. 'Karl Marx', niet 'Marx' of 'Karel Marx'). \
  start_seconds: het tijdstempel (in seconden) waarop deze persoon voor het eerst wordt genoemd; \
  gebruik de [MM:SS]-tijdstempels uit het transcript (bijv. [12:34] → 754).
- books: alleen boeken die expliciet bij naam worden genoemd én inhoudelijk worden besproken. \
  Geen titels die slechts terloops voorbijkomen. \
  start_seconds: het tijdstempel (in seconden) waarop het boek voor het eerst inhoudelijk ter sprake komt. \
  Gebruik de [MM:SS]-tijdstempels uit het transcript (bijv. [12:34] → 754).
- bible_refs: ALLEEN concrete verwijzingen naar bijbelboeken/hoofdstukken/verzen die werkelijk \
  worden aangehaald of geciteerd. NIET de Bijbel in het algemeen. \
  Gebruik Nederlandse boeknames (bijv. "Johannes 3:16", "Mattheus 5").
- places: geografische plaatsen die relevant zijn voor het gesprek.
- summary_tldr: maximaal 3 zinnen, in het Nederlands.
- summary_points: 5 tot 10 korte kernpunten die de rode draad van het gesprek beschrijven, in het Nederlands.
- chapters: verdeel het gesprek in 4 tot 8 logische delen. Gebruik de [MM:SS]-tijdstempels uit het \
  transcript om start_seconds te bepalen (bijv. [12:34] → 754). Elk hoofdstuk heeft een Nederlandse titel \
  en een korte samenvatting van 1-2 zinnen.
- highlights: 3 tot 6 opmerkelijke momenten — een verrassende uitspraak, een emotioneel moment, een \
  scherpe gedachte. Gebruik start_seconds van het bijbehorende transcript-segment. speaker is de \
  volledige naam van de spreker. text is de letterlijke of licht samengevatte uitspraak. note legt uit \
  waarom dit moment opvalt.
- keywords: 8 tot 12 sleutelwoorden die de inhoud van de aflevering het best karakteriseren. \
  Kies betekenisvolle termen: theologische concepten, eigennamen (personen, boeken, bewegingen), \
  centrale thema's. Gebruik enkelvoud of de meest gangbare vorm. Geen stopwoorden, geen generieke \
  woorden als "gesprek" of "podcast". In het Nederlands.
- quotes: maximaal 3 treffende uitspraken; haal ze letterlijk uit de afleveringsbeschrijving \
  (niet uit het transcript). Laat leeg als er geen goede citaten zijn.
"""


def _parse_json_response(text: str) -> dict:
    """Strip markdown fences, fix trailing commas, and parse JSON."""
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ```
    m = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text)
    if m:
        text = m.group(1).strip()
    # Remove trailing commas before ] or }
    text = re.sub(r',\s*([\]}])', r'\1', text)
    # If JSON appears cut off (unterminated), try to close open arrays/objects
    if not text.endswith('}'):
        # Count open braces/brackets
        depth = 0
        in_str = False
        escape = False
        for ch in text:
            if escape:
                escape = False
                continue
            if ch == '\\' and in_str:
                escape = True
                continue
            if ch == '"' and not escape:
                in_str = not in_str
                continue
            if not in_str:
                if ch in '{[':
                    depth += 1
                elif ch in ']}':
                    depth -= 1
        # Strip trailing incomplete entry (after last complete comma-separated item)
        text = re.sub(r',\s*\{[^{}]*$', '', text)
        text = re.sub(r',\s*"[^"]*$', '', text)
        text = re.sub(r',\s*$', '', text)
        # Close open structures
        while depth > 0:
            if depth == 1:
                text += '}'
            else:
                text += ']'
            depth -= 1
    return json.loads(text)


# ---------------------------------------------------------------------------
# Google Books enrichment
# ---------------------------------------------------------------------------

GOOGLE_BOOKS_URL = 'https://www.googleapis.com/books/v1/volumes'


def _search_google_books(title: str, author: str = '', api_key: str = '') -> list[dict]:
    """Return up to 5 Google Books candidates for a title (+ optional author)."""
    query = f'intitle:{title}'
    if author:
        query += f'+inauthor:{author}'
    params = {'q': query, 'maxResults': '5', 'printType': 'books'}
    if api_key:
        params['key'] = api_key
    url = GOOGLE_BOOKS_URL + '?' + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read().decode('utf-8'))
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                wait = 10 * (attempt + 1)
                print(f'    Google Books 429 for "{title}" — retrying in {wait}s …')
                time.sleep(wait)
            else:
                print(f'    Google Books request failed for "{title}": {exc}')
                return []
        except Exception as exc:
            print(f'    Google Books request failed for "{title}": {exc}')
            return []
    results = []
    for item in data.get('items', []):
        vi = item.get('volumeInfo', {})
        ids = {x['type']: x['identifier'] for x in vi.get('industryIdentifiers', [])}
        results.append({
            'volume_id': item['id'],
            'title': vi.get('title', ''),
            'subtitle': vi.get('subtitle', ''),
            'authors': vi.get('authors', []),
            'description': (vi.get('description', '') or '')[:400],
            'isbn13': ids.get('ISBN_13'),
            'isbn10': ids.get('ISBN_10'),
            'thumbnail': vi.get('imageLinks', {}).get('thumbnail', ''),
            'published': (vi.get('publishedDate', '') or '')[:4],
        })
    return results


def _verify_books(client, model: str, books: list[dict], episode_context: str) -> list[dict]:
    """Second LLM call: match extracted books to Google Books candidates."""
    if not books:
        return books

    book_candidates = []
    for book in books:
        candidates = _search_google_books(book.get('title', ''), book.get('author', ''),
                                          os.environ.get('GOOGLE_BOOKS_API_KEY', ''))
        book_candidates.append({'book': book, 'candidates': candidates})
        time.sleep(0.1)  # stay within Google's free-tier rate limit

    if not any(bc['candidates'] for bc in book_candidates):
        return books  # no results at all — return as-is

    prompt = (
        'Je krijgt boeken die zijn geëxtraheerd uit een podcastaflevering, '
        'samen met zoekresultaten van de Google Books API.\n\n'
        f'CONTEXT VAN DE AFLEVERING:\n{episode_context}\n\n'
        'BOEKEN MET GOOGLE BOOKS KANDIDATEN:\n'
        + json.dumps(book_candidates, ensure_ascii=False, indent=2)
        + '\n\nBepaal voor elk geëxtraheerd boek welke Google Books kandidaat '
        '(als die er is) het juiste boek is dat in de aflevering wordt besproken. '
        'Houd rekening met de context van het gesprek, de auteur en de beschrijving.\n\n'
        'Geef je antwoord als ALLEEN valide JSON — een array met één object per boek '
        'in DEZELFDE VOLGORDE als de invoer:\n\n'
        '[\n'
        '  {\n'
        '    "title": "originele titel uit extracted",\n'
        '    "matched": true,\n'
        '    "volume_id": "Google volume_id van de beste match",\n'
        '    "canonical_title": "officiële titel",\n'
        '    "canonical_author": "officiële auteur(s)",\n'
        '    "isbn13": "ISBN-13 of null",\n'
        '    "isbn10": "ISBN-10 of null",\n'
        '    "thumbnail": "thumbnail URL of leeg"\n'
        '  }\n'
        ']\n\n'
        'Als er geen goede match is zet matched op false en laat de andere velden weg. '
        'Geen markdown, geen uitleg, alleen JSON.'
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            output_config={'effort': 'low'},
            messages=[{'role': 'user', 'content': prompt}],
        )
        raw = next((b.text for b in response.content if b.type == 'text'), '[]')
        matches = _parse_json_response(raw)
        if not isinstance(matches, list):
            matches = []
    except Exception as exc:
        print(f'    Book verification LLM call failed: {exc}')
        return books

    enriched = []
    for i, book in enumerate(books):
        result = matches[i] if i < len(matches) else {}
        merged = dict(book)
        if result.get('matched'):
            merged['volume_id']       = result.get('volume_id', '')
            merged['canonical_title'] = result.get('canonical_title') or book.get('title', '')
            merged['canonical_author']= result.get('canonical_author') or book.get('author', '')
            merged['isbn13']          = result.get('isbn13')
            merged['isbn10']          = result.get('isbn10')
            merged['thumbnail']       = result.get('thumbnail', '')
        enriched.append(merged)
    return enriched


def _build_catalog_prompt(all_eps: list[dict], exclude_n) -> str:
    """Build a compact catalog of all episodes for the similarity prompt (cacheable)."""
    lines = [
        'Je bent redacteur van De Ongelooflijke Podcast. '
        'Hieronder staat de volledige catalogus van afleveringen. '
        'Formaat per regel: #nr | Titel | Thema\'s | Gasten | Beschrijving (eerste 120 tekens)\n',
    ]
    for e in all_eps:
        if e.get('n') == exclude_n:
            continue
        th = ', '.join(e.get('th', []))
        g  = ', '.join(e.get('g', []))
        xs = (e.get('x') or '').replace('\n', ' ')[:120]
        lines.append(f"#{e['n']} | {e['t']} | {th} | {g} | {xs}")
    return '\n'.join(lines)


def _recommend_similar(client, model: str, feed: dict, extracted: dict,
                       all_eps: list[dict]) -> list[dict]:
    """Third LLM call: pick 3–5 thematically similar episodes from the full catalogue."""
    current_n = feed.get('n')
    known_ns = {e.get('n') for e in all_eps}

    catalog_text = _build_catalog_prompt(all_eps, current_n)

    themes  = ', '.join(extracted.get('themes', []))
    guests  = ', '.join(extracted.get('guests', []))
    people  = ', '.join(p['name'] for p in extracted.get('people', []))
    tldr    = extracted.get('summary_tldr', '')

    user_prompt = (
        f'Zoek de 3 tot 5 afleveringen uit de catalogus die het meest lijken op deze aflevering.\n\n'
        f'HUIDIGE AFLEVERING:\n'
        f'#{current_n}: {feed.get("t", "")}\n'
        f'Thema\'s: {themes}\n'
        f'Gasten: {guests}\n'
        f'Besproken personen: {people}\n'
        f'Samenvatting: {tldr}\n\n'
        f'Selecteer op thematische gelijkenis, gedeelde figuren of overlappende onderwerpen. '
        f'Geef je antwoord als ALLEEN valide JSON — een array van objecten, '
        f'gesorteerd van meest naar minst gelijkend:\n'
        f'[{{"n": 123, "reason": "Korte reden in het Nederlands (max 15 woorden)"}}, ...]\n\n'
        f'Gebruik alleen nummers uit de catalogus. Geen markdown, geen uitleg.'
    )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=400,
            output_config={'effort': 'low'},
            system=[{
                'type': 'text',
                'text': catalog_text,
                'cache_control': {'type': 'ephemeral'},
            }],
            messages=[{'role': 'user', 'content': user_prompt}],
        )
        raw = next((b.text for b in response.content if b.type == 'text'), '[]')
        result = _parse_json_response(raw)
        if not isinstance(result, list):
            result = []
        # Validate: only keep entries with known, non-current episode numbers
        result = [
            r for r in result
            if isinstance(r.get('n'), int) and r['n'] in known_ns and r['n'] != current_n
        ]
        return result[:5]
    except Exception as exc:
        print(f'    Similar episodes LLM call failed: {exc}')
        return []


def _all_keys() -> list[str]:
    """Return episode keys that have both a feed snapshot and a transcript."""
    feed_keys = {p.stem for p in DIR_FEED.glob('*.json')}
    tr_keys   = {p.stem for p in DIR_TR.glob('*.json')}
    return sorted(feed_keys & tr_keys, key=lambda k: int(k) if k.isdigit() else 0)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyse_episode(key: str, client, model: str, system_prompt: str,
                    all_eps: list | None = None,
                    enrich_books: bool = True,
                    recommend_similar: bool = True) -> dict:
    feed = _load_feed(key)
    tr   = _load_transcript(key)
    if not feed or not tr:
        raise FileNotFoundError(f'Missing feed or transcript for episode {key}')

    transcript_text = _transcript_text(tr)

    user_content = (
        f"Aflevering #{feed.get('n', key)}: {feed.get('t', '')}\n"
        f"Datum: {feed.get('date', '')}\n\n"
        f"=== BESCHRIJVING ===\n{feed.get('desc', '').strip()}\n\n"
        f"=== TRANSCRIPT (eerste {len(transcript_text.splitlines())} regels) ===\n"
        f"{transcript_text}"
    )

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=[{
            'type': 'text',
            'text': system_prompt,
            'cache_control': {'type': 'ephemeral'},
        }],
        output_config={'effort': 'low'},
        messages=[{'role': 'user', 'content': user_content}],
    )

    raw_text = ''
    for block in response.content:
        if block.type == 'text':
            raw_text = block.text
            break

    extracted = _parse_json_response(raw_text)
    usage = response.usage

    # Enrich books with Google Books metadata + LLM verification
    if enrich_books and extracted.get('books'):
        print(f'    Enriching {len(extracted["books"])} book(s) via Google Books …')
        episode_context = (
            f"{feed.get('t', '')}\n"
            f"{extracted.get('summary_tldr', '')}"
        )
        extracted['books'] = _verify_books(client, model, extracted['books'], episode_context)
        matched = sum(1 for b in extracted['books'] if b.get('isbn13') or b.get('volume_id'))
        print(f'    Books matched: {matched}/{len(extracted["books"])}')

    # Recommend similar episodes via LLM
    if recommend_similar and all_eps:
        print(f'    Finding similar episodes …')
        extracted['similar'] = _recommend_similar(client, model, feed, extracted, all_eps)
        print(f'    Similar: {[s["n"] for s in extracted["similar"]]}')

    result = {
        'episode': feed.get('n', key),
        'analyzed': datetime.date.today().isoformat(),
        'model': model,
        'usage': {
            'input_tokens': usage.input_tokens,
            'output_tokens': usage.output_tokens,
            'cache_read_input_tokens': getattr(usage, 'cache_read_input_tokens', 0),
            'cache_creation_input_tokens': getattr(usage, 'cache_creation_input_tokens', 0),
        },
        **extracted,
    }
    return result


def save_analysis(key: str, data: dict) -> None:
    DIR_OUT.mkdir(parents=True, exist_ok=True)
    path = DIR_OUT / f'{key}.json'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Analyse podcast episodes with Claude.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--episode', type=str, help='Episode number or key to analyse')
    group.add_argument('--all-missing', action='store_true',
                       help='Analyse all episodes with transcript but no analysis file')
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'Claude model (default: {DEFAULT_MODEL})')
    parser.add_argument('--force', action='store_true', help='Re-analyse even if analysis already exists')
    parser.add_argument('--no-book-enrichment', action='store_true',
                        help='Skip Google Books lookup and LLM book verification')
    parser.add_argument('--no-similar', action='store_true',
                        help='Skip LLM similar-episode recommendation')
    args = parser.parse_args()

    try:
        import anthropic
    except ImportError:
        sys.exit('anthropic package not found — run: pip install anthropic')

    # Load .env from repo root if present
    env_path = ROOT / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                os.environ.setdefault(k.strip(), v.strip())

    # Accept ANTHROPIC_API_KEY or CLAUDE_API_KEY
    api_key = os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('CLAUDE_API_KEY')
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    themes = json.loads(THEMES_PATH.read_text(encoding='utf-8'))
    system_prompt = _build_system_prompt(themes)

    # Load full episode list for similar-episode recommendations
    all_eps = []
    if not args.no_similar and EPISODES_JSON.exists():
        try:
            all_eps = json.loads(EPISODES_JSON.read_text(encoding='utf-8')).get('eps', [])
            print(f'  Loaded {len(all_eps)} episodes for similarity matching.')
        except Exception as exc:
            print(f'  Warning: could not load episodes.json for similarity: {exc}')

    if args.episode:
        keys = [str(args.episode)]
    else:
        keys = _all_keys()
        if not args.force:
            existing = {p.stem for p in DIR_OUT.glob('*.json')}
            keys = [k for k in keys if k not in existing]

    if not keys:
        print('Nothing to analyse.')
        return

    print(f'Analysing {len(keys)} episode(s) with {args.model} …')
    total_cost_estimate = 0.0
    errors = []

    for i, key in enumerate(keys, 1):
        out_path = DIR_OUT / f'{key}.json'
        if not args.force and out_path.exists():
            print(f'  [{i}/{len(keys)}] #{key} — skipped (already exists)')
            continue

        try:
            data = analyse_episode(key, client, args.model, system_prompt,
                                   all_eps=all_eps,
                                   enrich_books=not args.no_book_enrichment,
                                   recommend_similar=not args.no_similar)
            save_analysis(key, data)
            u = data['usage']
            # Rough cost estimate for sonnet-5-5: $2.00/MTok input, $10.00/MTok output
            cost = (u['input_tokens'] * 2.00 + u['output_tokens'] * 10.00) / 1_000_000
            total_cost_estimate += cost
            cache_note = f" (cache_read={u['cache_read_input_tokens']})" if u.get('cache_read_input_tokens') else ''
            print(f'  [{i}/{len(keys)}] #{key} — OK  in={u["input_tokens"]} out={u["output_tokens"]}{cache_note}')
        except Exception as e:
            print(f'  [{i}/{len(keys)}] #{key} — ERROR: {e}')
            errors.append((key, str(e)))
            if 'rate' in str(e).lower() or '429' in str(e):
                print('    Rate limited — waiting 60 s …')
                time.sleep(60)

        # Small pause to avoid hammering the API
        if i < len(keys):
            time.sleep(0.3)

    print(f'\nDone. Estimated cost: ${total_cost_estimate:.4f}')
    if errors:
        print(f'Errors ({len(errors)}):')
        for k, msg in errors:
            print(f'  #{k}: {msg}')


if __name__ == '__main__':
    main()
