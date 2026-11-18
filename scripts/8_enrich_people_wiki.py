"""Enrich people in analysis files with Wikipedia data.

For each person in `data/analysis/{n}.json`, this script:
1. Searches nl.wikipedia.org (then en.wikipedia.org) for a matching article.
2. Calls Claude to verify the top candidates against the episode context.
3. Fetches the confirmed article's URL and thumbnail image.
4. Writes wiki_url, wiki_image, wiki_lang, wiki_checked back into the analysis file.

Usage:
    python scripts/8_enrich_people_wiki.py --episode 327
    python scripts/8_enrich_people_wiki.py --all-missing          # episodes with people but no wiki_checked
    python scripts/8_enrich_people_wiki.py --all-missing --force  # re-check everything

Requires:
    pip install anthropic
    ANTHROPIC_API_KEY env var (or ant auth login profile)

Wikipedia API: free, no API key required.
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.parse, urllib.error
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR_FEED     = ROOT / 'data' / 'feed'
DIR_ANALYSIS = ROOT / 'data' / 'analysis'

DEFAULT_MODEL = 'claude-haiku-5-5'

_HEADERS = {
    'User-Agent': 'OngelooflijkArchief/1.0 podcast-archief-tool',
    'Accept': 'application/json',
}

WIKI_LANGS = ['nl', 'en']
SEARCH_LIMIT = 4   # candidates per language
THUMB_SIZE   = 100  # px
WIKI_DELAY   = 1.0  # seconds between Wikipedia requests (200 req/min limit for bots)


# ---------------------------------------------------------------------------
# Wikipedia helpers
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def _wiki_get(url: str, retries: int = 4) -> dict:
    """GET a Wikipedia API URL with exponential backoff on 429."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
                wait = 2 ** (attempt + 1)  # 2, 4, 8, 16 s
                print(f'      Wikipedia 429 — waiting {wait}s …')
                time.sleep(wait)
            else:
                raise
    return {}


def wiki_search(name: str, lang: str = 'nl') -> list[dict]:
    """Return up to SEARCH_LIMIT Wikipedia search hits for `name`."""
    params = {
        'action': 'query',
        'list': 'search',
        'srsearch': name,
        'srlimit': str(SEARCH_LIMIT),
        'srnamespace': '0',
        'format': 'json',
    }
    url = f'https://{lang}.wikipedia.org/w/api.php?' + urllib.parse.urlencode(params)
    try:
        data = _wiki_get(url)
        results = data.get('query', {}).get('search', [])
        return [
            {
                'title': item['title'],
                'pageid': item['pageid'],
                'snippet': _strip_html(item.get('snippet', '')),
                'lang': lang,
            }
            for item in results
        ]
    except Exception as exc:
        print(f'      wiki_search failed ({lang} "{name}"): {exc}')
        return []


def wiki_pageinfo(pageid: int, lang: str = 'nl') -> dict:
    """Return {url, image} for a Wikipedia page id."""
    params = {
        'action': 'query',
        'prop': 'pageimages|info',
        'pageids': str(pageid),
        'pithumbsize': str(THUMB_SIZE),
        'inprop': 'url',
        'format': 'json',
    }
    url = f'https://{lang}.wikipedia.org/w/api.php?' + urllib.parse.urlencode(params)
    try:
        data = _wiki_get(url)
        pages = data.get('query', {}).get('pages', {})
        page = next(iter(pages.values()), {})
        return {
            'url':   page.get('fullurl', ''),
            'image': (page.get('thumbnail') or {}).get('source', ''),
        }
    except Exception as exc:
        print(f'      wiki_pageinfo failed (pageid={pageid}, {lang}): {exc}')
        return {}


# ---------------------------------------------------------------------------
# LLM verification
# ---------------------------------------------------------------------------

def _parse_json_response(text: str):
    text = text.strip()
    m = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text)
    if m:
        text = m.group(1).strip()
    text = re.sub(r',\s*([\]}])', r'\1', text)
    return json.loads(text)


def _verify_people(client, model: str, people_candidates: list[dict],
                   episode_context: str) -> list[dict]:
    """One LLM call to verify Wikipedia matches for a batch of people."""
    prompt = (
        'Je krijgt personen geëxtraheerd uit een podcastaflevering, '
        'samen met Wikipedia zoekresultaten.\n\n'
        f'CONTEXT VAN DE AFLEVERING:\n{episode_context}\n\n'
        'PERSONEN MET WIKIPEDIA KANDIDATEN:\n'
        + json.dumps(people_candidates, ensure_ascii=False, indent=2)
        + '\n\nBepaal voor elke persoon welke Wikipedia kandidaat (als die er is) '
        'overeenkomt met de persoon die in de aflevering wordt besproken. '
        'De kandidaat moet DEZELFDE persoon zijn; let op de note en de context.\n\n'
        'Geef je antwoord als ALLEEN valide JSON — een array met één object per persoon '
        'in DEZELFDE VOLGORDE als de invoer:\n\n'
        '[\n'
        '  {\n'
        '    "name": "naam uit de invoer",\n'
        '    "matched": true,\n'
        '    "pageid": 12345,\n'
        '    "lang": "nl"\n'
        '  }\n'
        ']\n\n'
        'Als er geen goede match is: matched=false, laat pageid en lang weg. '
        'Geen markdown, geen uitleg, alleen JSON.'
    )
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            output_config={'effort': 'low'},
            messages=[{'role': 'user', 'content': prompt}],
        )
        raw = next((b.text for b in response.content if b.type == 'text'), '[]')
        result = _parse_json_response(raw)
        return result if isinstance(result, list) else []
    except Exception as exc:
        print(f'    People wiki verification LLM call failed: {exc}')
        return []


# ---------------------------------------------------------------------------
# Main enrichment logic
# ---------------------------------------------------------------------------

def _fetch_pageinfo_for_person(p_obj: dict) -> bool:
    """Retry wiki_pageinfo for a person that has wiki_pageid but no wiki_url.
    Returns True if the URL was filled in."""
    pageid = p_obj.get('wiki_pageid')
    lang   = p_obj.get('wiki_lang', 'nl')
    if not pageid:
        return False
    info = wiki_pageinfo(int(pageid), lang)
    if info.get('url'):
        p_obj['wiki_url'] = info['url']
        if info.get('image'):
            p_obj['wiki_image'] = info['image']
        return True
    return False


def enrich_episode(key: str, client, model: str, force: bool = False) -> bool:
    """Enrich people for one episode. Returns True if the file was updated."""
    analysis_path = DIR_ANALYSIS / f'{key}.json'
    if not analysis_path.exists():
        return False

    analysis = json.loads(analysis_path.read_text(encoding='utf-8'))
    people = analysis.get('people', [])
    if not people:
        return False

    # Phase 1: retry pageinfo for people already matched but missing wiki_url
    pageinfo_retried = 0
    for p_obj in people:
        if p_obj.get('wiki_pageid') and not p_obj.get('wiki_url'):
            name = p_obj['name']
            if _fetch_pageinfo_for_person(p_obj):
                pageinfo_retried += 1
                print(f'      ✓ {name} (retry) → {p_obj["wiki_url"]}')
            else:
                print(f'      ~ {name} (retry): still no page URL')
            time.sleep(WIKI_DELAY)

    # Phase 2: LLM verification for people not yet checked
    to_check = people if force else [p for p in people if not p.get('wiki_checked')]
    if not to_check:
        if pageinfo_retried:
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'    Saved  ({pageinfo_retried} pageinfo retries)')
        return bool(pageinfo_retried)

    # Load episode context
    feed_path = DIR_FEED / f'{key}.json'
    feed = json.loads(feed_path.read_text(encoding='utf-8')) if feed_path.exists() else {}
    episode_context = (
        f"#{feed.get('n', key)}: {feed.get('t', '')}\n"
        f"{(feed.get('desc') or '')[:300]}\n\n"
        + '\n'.join(
            f"- {p['name']}: {p.get('note', '')}"
            for p in to_check
        )
    )

    # Search Wikipedia for each person (1 req/s to stay within rate limit)
    people_candidates = []
    for person in to_check:
        name = person['name']
        candidates = []
        for lang in WIKI_LANGS:
            hits = wiki_search(name, lang)
            candidates.extend(hits)
            time.sleep(WIKI_DELAY)
        people_candidates.append({
            'person': {'name': name, 'note': person.get('note', '')},
            'candidates': candidates[:6],
        })

    # LLM verification (one call for the whole batch)
    print(f'    Verifying {len(to_check)} person(s) …')
    matches = _verify_people(client, model, people_candidates, episode_context)

    # Build a map from name → analysis person object
    name_to_person = {p['name']: p for p in people}

    matched_count = 0
    for i, person_input in enumerate(to_check):
        result = matches[i] if i < len(matches) else {}
        p_obj = name_to_person.get(person_input['name'], person_input)
        p_obj['wiki_checked'] = True

        if result.get('matched') and result.get('pageid'):
            pageid = int(result['pageid'])
            lang   = result.get('lang', 'nl')
            # Always store pageid+lang so a re-run can retry pageinfo on 429
            p_obj['wiki_pageid'] = pageid
            p_obj['wiki_lang']   = lang
            info = wiki_pageinfo(pageid, lang)
            if info.get('url'):
                p_obj['wiki_url'] = info['url']
                if info.get('image'):
                    p_obj['wiki_image'] = info['image']
                matched_count += 1
                print(f'      ✓ {person_input["name"]} → {info["url"]}')
            else:
                print(f'      ~ {person_input["name"]} matched (pageid={pageid}) but pageinfo failed — will retry')
            time.sleep(WIKI_DELAY)
        else:
            print(f'      – {person_input["name"]}: no match')

    analysis_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'    Saved  ({matched_count}/{len(to_check)} matched)')
    return True


def _keys_needing_enrichment(force: bool) -> list[str]:
    keys = []
    for f in sorted(DIR_ANALYSIS.glob('*.json'), key=lambda p: int(p.stem) if p.stem.isdigit() else 0):
        try:
            an = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        people = an.get('people', [])
        if not people:
            continue
        needs_llm      = any(not p.get('wiki_checked') for p in people)
        needs_pageinfo = any(p.get('wiki_pageid') and not p.get('wiki_url') for p in people)
        if force or needs_llm or needs_pageinfo:
            keys.append(f.stem)
    return keys


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Enrich analysis people with Wikipedia data.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--episode', type=str, help='Episode number to enrich')
    group.add_argument('--all-missing', action='store_true',
                       help='Enrich all episodes that have un-checked people')
    parser.add_argument('--model', default=DEFAULT_MODEL,
                        help=f'Claude model (default: {DEFAULT_MODEL})')
    parser.add_argument('--force', action='store_true',
                        help='Re-check even already wiki_checked people')
    args = parser.parse_args()

    try:
        import anthropic
    except ImportError:
        sys.exit('anthropic package not found — run: pip install anthropic')

    env_path = ROOT / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                os.environ.setdefault(k.strip(), v.strip())

    api_key = os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('CLAUDE_API_KEY')
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    keys = [str(args.episode)] if args.episode else _keys_needing_enrichment(args.force)

    if not keys:
        print('Nothing to enrich.')
        return

    print(f'Enriching {len(keys)} episode(s) with {args.model} …')

    for i, key in enumerate(keys, 1):
        print(f'  [{i}/{len(keys)}] #{key}')
        try:
            enrich_episode(key, client, args.model, force=args.force)
        except Exception as exc:
            print(f'    ERROR: {exc}')
            if '429' in str(exc) or 'rate' in str(exc).lower():
                print('    Rate limited — waiting 60 s …')
                time.sleep(60)
        if i < len(keys):
            time.sleep(0.3)

    print('Done.')


if __name__ == '__main__':
    main()
