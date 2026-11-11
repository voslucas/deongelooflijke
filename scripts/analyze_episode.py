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
"""
import argparse, json, os, re, sys, time, datetime
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIR_FEED = ROOT / 'data' / 'feed'
DIR_TR   = ROOT / 'data' / 'transcripts'
DIR_OUT  = ROOT / 'data' / 'analysis'
THEMES_PATH = ROOT / 'data' / 'themes.json'

DEFAULT_MODEL = 'claude-haiku-5-5'
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
  "people": [ {{"name": "Volledige Naam", "note": "korte rol of beschrijving"}} ],
  "books": [ {{"title": "Boektitel", "author": "Auteur of leeg", "note": "optioneel"}} ],
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
  "quotes": [ "citaat" ]
}}

REGELS:
- themes: kies maximaal 4 uit deze vaste lijst (kopieer het label exact):
{theme_labels}
- guests: directe gesprekspartners, NIET David Boogerd en NIET Stefan Paas.
- people: personen die besproken worden (ook historische figuren, politici, filosofen). \
  Normaliseer namen consistent (bijv. 'Karl Marx', niet 'Marx' of 'Karel Marx').
- books: alleen boeken die expliciet bij naam worden genoemd én inhoudelijk worden besproken. \
  Geen titels die slechts terloops voorbijkomen.
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


def _all_keys() -> list[str]:
    """Return episode keys that have both a feed snapshot and a transcript."""
    feed_keys = {p.stem for p in DIR_FEED.glob('*.json')}
    tr_keys   = {p.stem for p in DIR_TR.glob('*.json')}
    return sorted(feed_keys & tr_keys, key=lambda k: int(k) if k.isdigit() else 0)


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyse_episode(key: str, client, model: str, system_prompt: str) -> dict:
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
        max_tokens=6000,
        system=[{
            'type': 'text',
            'text': system_prompt,
            'cache_control': {'type': 'ephemeral'},
        }],
        messages=[{'role': 'user', 'content': user_content}],
    )

    raw_text = ''
    for block in response.content:
        if block.type == 'text':
            raw_text = block.text
            break

    extracted = _parse_json_response(raw_text)
    usage = response.usage

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
            data = analyse_episode(key, client, args.model, system_prompt)
            save_analysis(key, data)
            u = data['usage']
            # Rough cost estimate for haiku-5-5: $0.10/MTok input, $0.50/MTok output
            cost = (u['input_tokens'] * 0.10 + u['output_tokens'] * 0.50) / 1_000_000
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
