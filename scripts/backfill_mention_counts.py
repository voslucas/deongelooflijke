"""One-time backfill: add mention_count to existing people[] entries in analysis JSONs.

For each analysis file that has people[] entries without mention_count, this script:
1. Loads the matching transcript
2. Asks claude-haiku-5-5 to count how many times each person is mentioned,
   given their already-extracted name and the full transcript text
3. Patches the analysis JSON in-place (adds mention_count to each person entry)

The answer is always at least 1 (the LLM found this person during the original
analysis, so they must appear at least once).

Usage:
    python scripts/backfill_mention_counts.py
    python scripts/backfill_mention_counts.py --episode 327
    python scripts/backfill_mention_counts.py --dry-run
"""
import argparse, json, os, re, sys, time, datetime, unicodedata
import pathlib

ROOT         = pathlib.Path(__file__).resolve().parent.parent
DIR_TR       = ROOT / 'data' / 'transcripts'
DIR_ANALYSIS = ROOT / 'data' / 'analysis'

DEFAULT_MODEL = 'claude-haiku-5-5'
MAX_TRANSCRIPT_CHARS = 60_000

# ---------------------------------------------------------------------------
# Shared helpers (duplicated from analyze_episode.py to keep script standalone)
# ---------------------------------------------------------------------------

def _transcript_text(tr: dict) -> str:
    speaker_map = {sp['id']: sp['name'] for sp in tr.get('speakers', [])}
    lines = []
    for seg in tr.get('segments', []):
        name = speaker_map.get(seg.get('speaker', ''), seg.get('speaker', '?'))
        text = seg.get('text', '').strip()
        if not text:
            continue
        mm, ss = divmod(int(seg.get('start', 0)), 60)
        lines.append(f'[{mm:02d}:{ss:02d}] {name}: {text}')
    full = '\n'.join(lines)
    if len(full) > MAX_TRANSCRIPT_CHARS:
        full = full[:MAX_TRANSCRIPT_CHARS] + '\n[... transcript ingekort ...]'
    return full


def _fix_control_chars(text: str) -> str:
    result = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == '\\':
            result.append(ch)
            if in_string:
                escape = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ord(ch) < 0x20:
            result.append({'\\n': '\n', '\r': '\\r', '\t': '\\t'}.get(ch, f'\\u{ord(ch):04x}'))
        else:
            result.append(ch)
    return ''.join(result)


def _parse_json_response(text: str) -> object:
    text = text.strip()
    m = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text)
    if m:
        text = m.group(1).strip()
    text = _fix_control_chars(text)
    text = re.sub(r'(?<!["\w])None(?!["\w])', 'null', text)
    text = re.sub(r'(?<!["\w])True(?!["\w])', 'true', text)
    text = re.sub(r'(?<!["\w])False(?!["\w])', 'false', text)
    text = re.sub(r',\s*([\]}])', r'\1', text)
    return json.loads(text)


# ---------------------------------------------------------------------------
# Count mentions via Haiku
# ---------------------------------------------------------------------------

def _count_mentions(client, model: str, people: list[dict], transcript: str) -> list[int]:
    """Return a list of mention counts (same order as people[]).

    Each count is the number of times the person is referred to in the transcript,
    including by name, surname, nickname, role, or clear contextual reference. At least 1.
    """
    names = [p['name'] for p in people]
    names_json = json.dumps(names, ensure_ascii=False)

    prompt = (
        'You are given a list of people and a Dutch podcast transcript.\n'
        'For each person, count how many times they are referred to in the transcript.\n\n'
        'Count ALL of the following as a reference:\n'
        '- Full name (e.g. "Donald Trump")\n'
        '- Surname or nickname (e.g. "Trump")\n'
        '- Role or title when it unambiguously identifies this person in context '
        '(e.g. "the American president", "de paus", "de filosoof", "the author")\n'
        '- Discourse references where context makes clear this person is meant '
        '(e.g. "what he said", "zijn boek", "de man die we net noemden")\n\n'
        'Do NOT count bare pronouns (hij/zij/he/she) unless the surrounding sentence '
        'makes the referent unambiguous.\n\n'
        f'PEOPLE:\n{names_json}\n\n'
        f'TRANSCRIPT:\n{transcript}\n\n'
        'Respond with ONLY a valid JSON array of integers in THE SAME ORDER as the input list. '
        'Each number is the count for that person. Minimum is 1 — every person was already '
        'confirmed present by a prior analysis. No markdown, no explanation, only the array.\n\n'
        'Example: [3, 1, 7]'
    )

    response = client.messages.create(
        model=model,
        max_tokens=500,
        messages=[{'role': 'user', 'content': prompt}],
    )
    raw = next((b.text for b in response.content if b.type == 'text'), '[]')
    try:
        counts = _parse_json_response(raw)
        if not isinstance(counts, list):
            raise ValueError('not a list')
        # Coerce to int, floor at 1
        return [max(1, int(c)) for c in counts]
    except Exception as exc:
        print(f'      Warning: could not parse counts response ({exc}) — defaulting to 1')
        return [1] * len(people)


# ---------------------------------------------------------------------------
# Per-episode logic
# ---------------------------------------------------------------------------

def _needs_backfill(analysis: dict) -> bool:
    """True if any people[] entry is missing mention_count."""
    return any('mention_count' not in p for p in analysis.get('people', []))


def backfill_episode(key: str, client, model: str, dry_run: bool, force: bool = False) -> bool:
    """Returns True if the file was (or would be) updated."""
    analysis_path = DIR_ANALYSIS / f'{key}.json'
    tr_path       = DIR_TR       / f'{key}.json'

    if not analysis_path.exists():
        return False

    analysis = json.loads(analysis_path.read_text(encoding='utf-8'))
    people   = analysis.get('people', [])

    if not people:
        return False

    if not force and not _needs_backfill(analysis):
        return False  # already complete

    if not tr_path.exists():
        print(f'  #{key} — no transcript, skipping')
        return False

    tr       = json.loads(tr_path.read_text(encoding='utf-8'))
    transcript = _transcript_text(tr)

    # With --force recount all entries; otherwise only those missing the field
    missing_idx = list(range(len(people))) if force else [i for i, p in enumerate(people) if 'mention_count' not in p]
    missing_people = [people[i] for i in missing_idx]

    print(f'  #{key} — counting mentions for {len(missing_people)} person(s) …', flush=True)

    if dry_run:
        print(f'      [dry-run] would call {model} for: {[p["name"] for p in missing_people]}')
        return True

    counts = _count_mentions(client, model, missing_people, transcript)

    patched = []
    for idx, count in zip(missing_idx, counts):
        people[idx]['mention_count'] = count
        patched.append(idx)

    analysis['people'] = people
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = ', '.join(f'{people[i]["name"]}={people[i]["mention_count"]}' for i in patched)
    print(f'      Updated: {summary}')
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Backfill mention_count into existing analysis files.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--episode', type=str, help='Single episode to backfill')
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'Claude model (default: {DEFAULT_MODEL})')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without calling the LLM')
    parser.add_argument('--force', action='store_true', help='Recount all entries, even those that already have mention_count')
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
    client  = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    if args.episode:
        keys = [str(args.episode)]
    else:
        keys = sorted(
            (p.stem for p in DIR_ANALYSIS.glob('*.json') if p.stem.isdigit()),
            key=int,
        )

    updated = 0
    for key in keys:
        if backfill_episode(key, client, args.model, args.dry_run, force=args.force):
            updated += 1
            if not args.dry_run:
                time.sleep(0.1)  # stay within rate limits

    action = 'would update' if args.dry_run else 'updated'
    print(f'\nDone — {action} {updated} analysis file(s).')


if __name__ == '__main__':
    main()
