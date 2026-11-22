"""Enrich people in analysis files with Wikipedia data.

For each person in `data/analysis/{n}.json`, this script:
1. Looks up `data/wiki_cache.json` — if the name was searched before, reuses that result.
2. Otherwise searches via the Wikimedia Core REST API (api.wikimedia.org) — nl first, en only
   as fallback when nl returns nothing. Each result includes the thumbnail inline.
3. Calls Claude (Haiku) once per episode to verify the best match against episode context.
4. Writes wiki_url, wiki_image, wiki_lang, wiki_pageid, wiki_checked into the analysis file.
5. Saves search results to `data/wiki_cache.json` so repeated names are never re-fetched.

Usage:
    python scripts/8_enrich_people_wiki.py --episode 327
    python scripts/8_enrich_people_wiki.py --all-missing
    python scripts/8_enrich_people_wiki.py --all-missing --force

Requires:
    pip install anthropic
    ANTHROPIC_API_KEY env var (or .env file)

Wikipedia: free, no API key required. Uses api.wikimedia.org/core/v1 (the app-tier REST API).
The cross-episode cache (`data/wiki_cache.json`) means each unique person name is fetched at
most once across all episodes, drastically reducing API calls on `--all-missing` runs.
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.parse, urllib.error
import pathlib

ROOT         = pathlib.Path(__file__).resolve().parent.parent
DIR_FEED     = ROOT / 'data' / 'feed'
DIR_ANALYSIS = ROOT / 'data' / 'analysis'
CACHE_PATH   = ROOT / 'data' / 'wiki_cache.json'

DEFAULT_MODEL = 'claude-haiku-5-5'

# Wikimedia Core REST API — designed for applications, not the action API.
# User-Agent format per Wikimedia policy: AppName/version (contact-URL-or-email)
_BASE = 'https://api.wikimedia.org/core/v1/wikipedia'
_HEADERS = {
    'User-Agent': 'OngelooflijkArchief/1.0 (https://github.com/deongelooflijke)',
    'Accept': 'application/json',
}

WIKI_LANGS   = ['nl', 'en']
SEARCH_LIMIT = 5    # candidates per language
WIKI_DELAY   = 1.0  # seconds between live API requests


# ---------------------------------------------------------------------------
# Search cache (data/wiki_cache.json)
# Keys: "{lang}:{name}" → list of candidate dicts (or [] if no results).
# A missing key means "never searched". A cached [] means "searched, found nothing".
# 429 / network failures are NOT cached so the name is retried next run.
# ---------------------------------------------------------------------------

def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')


# ---------------------------------------------------------------------------
# Wikimedia Core REST API helpers
# ---------------------------------------------------------------------------

def _wiki_get(url: str, retries: int = 4) -> dict:
    """GET with exponential backoff on 429 (2→4→8→16 s). Raises on final failure."""
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


def wiki_search(name: str, lang: str = 'nl') -> list[dict] | None:
    """Search Wikipedia via the Core REST API.

    Returns list of candidates {title, key, pageid, snippet, thumbnail_url, lang},
    [] if the search succeeded but found nothing, or None on network / 429 error
    (None is never cached so the name is retried next run).
    """
    params = urllib.parse.urlencode({'q': name, 'limit': str(SEARCH_LIMIT)})
    url = f'{_BASE}/{lang}/search/page?{params}'
    try:
        data = _wiki_get(url)
        results = []
        for page in data.get('pages', []):
            thumb = page.get('thumbnail') or {}
            img = thumb.get('url', '')
            if img.startswith('//'):
                img = 'https:' + img
            # Bump thumbnail to 250px — a standard Wikimedia size (pattern: /Npx-filename)
            img = re.sub(r'/\d+px-', '/250px-', img).split('?')[0]
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
        return None  # do not cache failures


def wiki_search_cached(name: str, lang: str, cache: dict) -> list[dict]:
    """Like wiki_search but reads/writes the shared search cache.

    Returns [] for a successful empty search; raises on a network failure.
    """
    key = f'{lang}:{name}'
    if key in cache:
        return cache[key]
    results = wiki_search(name, lang)
    if results is None:
        raise RuntimeError(f'Wikipedia search unavailable for {lang}:{name}; retry later')
    cache[key] = results   # cache success (even [])
    return results


def wiki_page_url(key: str, lang: str = 'nl') -> str:
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
            max_tokens=max(2000, len(people_candidates) * 100 + 1000),
            output_config={'effort': 'low'},
            messages=[{'role': 'user', 'content': prompt}],
        )
        raw = next((b.text for b in response.content if b.type == 'text'), '[]')
        result = _parse_json_response(raw)
        if response.stop_reason == 'max_tokens' or not isinstance(result, list) or len(result) != len(people_candidates):
            raise ValueError('Incomplete Wikipedia verification response')
        return result
    except Exception as exc:
        print(f'    LLM verification failed: {exc}')
        raise


# ---------------------------------------------------------------------------
# Main enrichment logic
# ---------------------------------------------------------------------------

def enrich_episode(key: str, client, model: str, cache: dict,
                   force: bool = False) -> bool:
    """Enrich people for one episode. Returns True if the analysis file was updated."""
    analysis_path = DIR_ANALYSIS / f'{key}.json'
    if not analysis_path.exists():
        return False

    analysis = json.loads(analysis_path.read_text(encoding='utf-8'))
    people = analysis.get('people', [])
    if not people:
        return False

    name_to_person = {p['name']: p for p in people}

    # Phase 1: resolve any person with wiki_pageid+wiki_lang but no wiki_url
    # (prior run stored the match but url derivation failed).
    pageinfo_fixed = 0
    for p_obj in people:
        if p_obj.get('wiki_pageid') and p_obj.get('wiki_lang') and not p_obj.get('wiki_url'):
            lang = p_obj['wiki_lang']
            name = p_obj['name']
            hits = wiki_search_cached(name, lang, cache)
            match = next((h for h in hits if h['pageid'] == p_obj['wiki_pageid']), None)
            if match:
                p_obj['wiki_url'] = wiki_page_url(match['key'], lang)
                if match['thumbnail_url'] and not p_obj.get('wiki_image'):
                    p_obj['wiki_image'] = match['thumbnail_url']
                pageinfo_fixed += 1
                print(f'      ✓ {name} (resolved) → {p_obj["wiki_url"]}')
            else:
                print(f'      ~ {name}: pageid {p_obj["wiki_pageid"]} not in top results')
            # only sleep if we actually hit the network (not a cache hit)
            cache_key = f'{lang}:{name}'
            if cache_key not in cache:
                time.sleep(WIKI_DELAY)

    # Phase 2: search + LLM verify for unchecked people
    to_check = people if force else [p for p in people if not p.get('wiki_checked')]
    if not to_check:
        if pageinfo_fixed:
            analysis_path.write_text(
                json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'    Saved  ({pageinfo_fixed} resolved)')
        return bool(pageinfo_fixed)

    # Load episode context for LLM
    feed_path = DIR_FEED / f'{key}.json'
    feed = json.loads(feed_path.read_text(encoding='utf-8')) if feed_path.exists() else {}
    episode_context = (
        f"#{feed.get('n', key)}: {feed.get('t', '')}\n"
        f"{(feed.get('desc') or '')[:300]}\n\n"
        + '\n'.join(f"- {p['name']}: {p.get('note', '')}" for p in to_check)
    )

    # Gather candidates — from cache where possible, live API otherwise.
    # nl first; en only if nl returns nothing.
    cache_hits = 0
    people_candidates = []
    for person in to_check:
        candidates = []
        for lang in WIKI_LANGS:
            cache_key = f'{lang}:{person["name"]}'
            already_cached = cache_key in cache
            hits = wiki_search_cached(person['name'], lang, cache)
            candidates.extend(hits)
            if not already_cached:
                time.sleep(WIKI_DELAY)  # only throttle live requests
            else:
                cache_hits += 1
            if hits:
                break  # nl had results — skip en
        people_candidates.append({
            'person': {'name': person['name'], 'note': person.get('note', '')},
            'candidates': candidates[:8],
        })

    if cache_hits:
        print(f'    {cache_hits} name(s) served from cache')

    # LLM verification — one call for the whole episode
    print(f'    Verifying {len(to_check)} person(s) …')
    matches = _verify_people(client, model, people_candidates, episode_context)

    # Build pageid → candidate lookup across all people
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
            pageid    = int(result['pageid'])
            lang      = result.get('lang', 'nl')
            p_obj['wiki_pageid'] = pageid
            p_obj['wiki_lang']   = lang

            candidate = all_candidates.get((pageid, lang))
            if candidate:
                p_obj['wiki_url'] = wiki_page_url(candidate['key'], lang)
                if candidate['thumbnail_url']:
                    p_obj['wiki_image'] = candidate['thumbnail_url']
                matched_count += 1
                print(f'      ✓ {person_input["name"]} → {p_obj["wiki_url"]}')
            else:
                # LLM chose a pageid not in our result set — do one extra search
                hits = wiki_search_cached(person_input['name'], lang, cache)
                match = next((h for h in hits if h['pageid'] == pageid), None)
                if match:
                    p_obj['wiki_url'] = wiki_page_url(match['key'], lang)
                    if match['thumbnail_url']:
                        p_obj['wiki_image'] = match['thumbnail_url']
                    matched_count += 1
                    print(f'      ✓ {person_input["name"]} → {p_obj["wiki_url"]}')
                else:
                    print(f'      ~ {person_input["name"]}: matched but key not found')
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
        needs_llm     = any(not p.get('wiki_checked') for p in people)
        needs_resolve = any(p.get('wiki_pageid') and not p.get('wiki_url') for p in people)
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

    cache = _load_cache()
    print(f'Enriching {len(keys)} episode(s) with {args.model} '
          f'({len(cache)} name(s) already cached) …')

    errors = []
    for i, key in enumerate(keys, 1):
        print(f'  [{i}/{len(keys)}] #{key}')
        try:
            enrich_episode(key, client, args.model, cache, force=args.force)
        except Exception as exc:
            print(f'    ERROR: {exc}')
            errors.append(key)
            if '429' in str(exc):
                print('    Rate limited — waiting 60 s …')
                time.sleep(60)
        finally:
            _save_cache(cache)  # retain successful searches even if a later call failed
        if i < len(keys):
            time.sleep(0.3)  # small gap between episodes (actual throttle is per-request)

    print('Done.')
    if errors:
        sys.exit(1)


if __name__ == '__main__':
    main()
