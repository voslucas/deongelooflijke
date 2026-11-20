"""Enrich people in analysis files with Wikipedia data.

For each person in `data/analysis/{n}.json`, this script:
1. Searches via the Wikimedia Core REST API (api.wikimedia.org) — nl first, then en.
   Each search result already includes the thumbnail, so no separate pageinfo call is needed.
2. Calls Claude (Haiku) once per episode batch to verify the best match against context.
3. Writes wiki_url, wiki_image, wiki_lang, wiki_pageid, wiki_checked into the analysis file.

Usage:
    python scripts/8_enrich_people_wiki.py --episode 327
    python scripts/8_enrich_people_wiki.py --all-missing
    python scripts/8_enrich_people_wiki.py --all-missing --force

Requires:
    pip install anthropic
    ANTHROPIC_API_KEY env var (or .env file)

Wikipedia: free, no API key required. Uses api.wikimedia.org/core/v1 (the app-tier REST API)
which has generous rate limits and returns thumbnails inline with search results.
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.parse, urllib.error
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR_FEED     = ROOT / 'data' / 'feed'
DIR_ANALYSIS = ROOT / 'data' / 'analysis'

DEFAULT_MODEL = 'claude-haiku-5-5'

# Wikimedia Core REST API — designed for applications, not the action API
_BASE = 'https://api.wikimedia.org/core/v1/wikipedia'

# User-Agent is required; format: AppName/version (contact)
_HEADERS = {
    'User-Agent': 'OngelooflijkArchief/1.0 (podcast-archief)',
    'Accept': 'application/json',
}

WIKI_LANGS   = ['nl', 'en']
SEARCH_LIMIT = 5    # candidates per language
WIKI_DELAY   = 1.0  # seconds between requests


# ---------------------------------------------------------------------------
# Wikimedia Core REST API helpers
# ---------------------------------------------------------------------------

def _wiki_get(url: str, retries: int = 4) -> dict:
    """GET with exponential backoff on 429 (2→4→8→16 s)."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                print(f'      429 — waiting {wait}s …')
                time.sleep(wait)
            else:
                raise
    return {}


def wiki_search(name: str, lang: str = 'nl') -> list[dict]:
    """Search Wikipedia via the Core REST API.

    Returns candidates as {title, key, pageid, snippet, thumbnail_url, lang}.
    The thumbnail is already included — no separate pageinfo call needed.
    """
    params = urllib.parse.urlencode({'q': name, 'limit': str(SEARCH_LIMIT)})
    url = f'{_BASE}/{lang}/search/page?{params}'
    try:
        data = _wiki_get(url)
        results = []
        for page in data.get('pages', []):
            thumb = page.get('thumbnail') or {}
            # thumbnail.url is protocol-relative (//upload.wikimedia.org/…)
            img = thumb.get('url', '')
            if img.startswith('//'):
                img = 'https:' + img
            # Bump thumbnail to 240px (pattern: /Npx-filename → /240px-filename)
            img = re.sub(r'/\d+px-', '/240px-', img).split('?')[0]
            results.append({
                'title':         page.get('title', ''),
                'key':           page.get('key', ''),
                'pageid':        page.get('id'),
                'snippet':       re.sub(r'<[^>]+>', '', page.get('excerpt', '')).strip(),
                'thumbnail_url': img,
                'lang':          lang,
            })
        return results
    except Exception as exc:
        print(f'      wiki_search failed ({lang} "{name}"): {exc}')
        return []


def wiki_page_url(key: str, lang: str = 'nl') -> str:
    """Construct the canonical Wikipedia page URL from a key."""
    return f'https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(key, safe=":/")}'


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
        print(f'    LLM verification failed: {exc}')
        return []


# ---------------------------------------------------------------------------
# Main enrichment logic
# ---------------------------------------------------------------------------

def enrich_episode(key: str, client, model: str, force: bool = False) -> bool:
    """Enrich people for one episode. Returns True if the file was updated."""
    analysis_path = DIR_ANALYSIS / f'{key}.json'
    if not analysis_path.exists():
        return False

    analysis = json.loads(analysis_path.read_text(encoding='utf-8'))
    people = analysis.get('people', [])
    if not people:
        return False

    # Build a name → person-object map for in-place updates
    name_to_person = {p['name']: p for p in people}

    # Phase 1: re-resolve any person that has wiki_pageid+wiki_lang but no wiki_url
    # (prior run stored the match but the pageinfo call failed — now we derive the
    #  URL directly from the key, so we don't need an extra API call at all)
    pageinfo_fixed = 0
    for p_obj in people:
        if p_obj.get('wiki_pageid') and p_obj.get('wiki_lang') and not p_obj.get('wiki_url'):
            # We stored pageid but not the page key; fall back to a quick search
            # to get the key, then construct the URL
            lang = p_obj['wiki_lang']
            name = p_obj['name']
            hits = wiki_search(name, lang)
            match = next((h for h in hits if h['pageid'] == p_obj['wiki_pageid']), None)
            if match:
                p_obj['wiki_url'] = wiki_page_url(match['key'], lang)
                if match['thumbnail_url'] and not p_obj.get('wiki_image'):
                    p_obj['wiki_image'] = match['thumbnail_url']
                pageinfo_fixed += 1
                print(f'      ✓ {name} (resolved) → {p_obj["wiki_url"]}')
            else:
                print(f'      ~ {name}: pageid {p_obj["wiki_pageid"]} not in top results')
            time.sleep(WIKI_DELAY)

    # Phase 2: LLM verification for people not yet checked
    to_check = people if force else [p for p in people if not p.get('wiki_checked')]
    if not to_check:
        if pageinfo_fixed:
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'    Saved  ({pageinfo_fixed} resolved)')
        return bool(pageinfo_fixed)

    # Load episode context
    feed_path = DIR_FEED / f'{key}.json'
    feed = json.loads(feed_path.read_text(encoding='utf-8')) if feed_path.exists() else {}
    episode_context = (
        f"#{feed.get('n', key)}: {feed.get('t', '')}\n"
        f"{(feed.get('desc') or '')[:300]}\n\n"
        + '\n'.join(f"- {p['name']}: {p.get('note', '')}" for p in to_check)
    )

    # Search Wikipedia for each person — nl first, en only as fallback
    people_candidates = []
    for person in to_check:
        candidates = []
        for lang in WIKI_LANGS:
            hits = wiki_search(person['name'], lang)
            candidates.extend(hits)
            time.sleep(WIKI_DELAY)
            if hits:
                break  # Dutch results found — skip English search
        people_candidates.append({
            'person': {'name': person['name'], 'note': person.get('note', '')},
            'candidates': candidates[:8],
        })

    # LLM verification — one call for the whole batch
    print(f'    Verifying {len(to_check)} person(s) …')
    matches = _verify_people(client, model, people_candidates, episode_context)

    # Build a lookup: pageid → candidate (across all people_candidates)
    all_candidates: dict[tuple, dict] = {}
    for pc in people_candidates:
        for c in pc['candidates']:
            if c['pageid']:
                all_candidates[(c['pageid'], c['lang'])] = c

    matched_count = 0
    for i, person_input in enumerate(to_check):
        result = matches[i] if i < len(matches) else {}
        p_obj = name_to_person.get(person_input['name'], person_input)
        p_obj['wiki_checked'] = True

        if result.get('matched') and result.get('pageid'):
            pageid = int(result['pageid'])
            lang   = result.get('lang', 'nl')
            p_obj['wiki_pageid'] = pageid
            p_obj['wiki_lang']   = lang

            # Find the candidate to get key and thumbnail (no extra API call)
            candidate = all_candidates.get((pageid, lang))
            if candidate:
                p_obj['wiki_url'] = wiki_page_url(candidate['key'], lang)
                if candidate['thumbnail_url']:
                    p_obj['wiki_image'] = candidate['thumbnail_url']
                matched_count += 1
                print(f'      ✓ {person_input["name"]} → {p_obj["wiki_url"]}')
            else:
                # pageid not in our result set — construct URL and try one search
                hits = wiki_search(person_input['name'], lang)
                match = next((h for h in hits if h['pageid'] == pageid), None)
                if match:
                    p_obj['wiki_url'] = wiki_page_url(match['key'], lang)
                    if match['thumbnail_url']:
                        p_obj['wiki_image'] = match['thumbnail_url']
                    matched_count += 1
                    print(f'      ✓ {person_input["name"]} → {p_obj["wiki_url"]}')
                else:
                    print(f'      ~ {person_input["name"]}: matched but key not found')
                time.sleep(WIKI_DELAY)
        else:
            print(f'      – {person_input["name"]}: no match')

    analysis_path.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'    Saved  ({matched_count}/{len(to_check)} matched)')
    return True


def _keys_needing_enrichment(force: bool) -> list[str]:
    keys = []
    for f in sorted(DIR_ANALYSIS.glob('*.json'),
                    key=lambda p: int(p.stem) if p.stem.isdigit() else 0):
        try:
            an = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        people = an.get('people', [])
        if not people:
            continue
        needs_llm      = any(not p.get('wiki_checked') for p in people)
        needs_resolve  = any(p.get('wiki_pageid') and not p.get('wiki_url') for p in people)
        if force or needs_llm or needs_resolve:
            keys.append(f.stem)
    return keys


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Enrich analysis people with Wikipedia data.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--episode', type=str, help='Episode number to enrich')
    group.add_argument('--all-missing', action='store_true',
                       help='Enrich all episodes with un-checked or unresolved people')
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
            if '429' in str(exc):
                print('    Rate limited — waiting 30 s …')
                time.sleep(30)
        if i < len(keys):
            time.sleep(0.5)

    print('Done.')


if __name__ == '__main__':
    main()
