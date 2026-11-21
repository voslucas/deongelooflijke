#!/usr/bin/env python3
"""
Backfill start_seconds for existing bible_refs in analysis files.

For each analysis file that has bible_refs without start_seconds, this script:
1. Loads the matching transcript
2. Calls Haiku 5.5 with the transcript + episode description to find start_seconds
3. Updates the analysis file in-place

Usage:
  python scripts/backfill_bible_start_seconds.py [--dry-run] [--episode N]
"""

import argparse
import json
import os
import pathlib
import re
import sys
import time

import anthropic

ROOT = pathlib.Path(__file__).resolve().parent.parent
ANALYSIS_DIR = ROOT / 'data' / 'analysis'
TRANSCRIPT_DIR = ROOT / 'data' / 'transcripts'


def _load_dotenv():
    """Load .env from project root if present (no dependency on python-dotenv)."""
    env_file = ROOT / '.env'
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv()


def ts_fmt(secs):
    s = max(0, round(secs))
    h, rem = divmod(s, 3600)
    m, x = divmod(rem, 60)
    if h:
        return f'{h}:{m:02d}:{x:02d}'
    return f'{m}:{x:02d}'


def format_transcript_for_prompt(segments, max_chars=100000):
    """Format transcript segments as timestamped lines for the LLM prompt."""
    lines = []
    for seg in segments:
        start = seg.get('start', 0)
        speaker = seg.get('speaker', '')
        text = (seg.get('text') or '').strip()
        if text:
            lines.append(f'[{ts_fmt(start)}] {speaker}: {text}')
    full = '\n'.join(lines)
    if len(full) > max_chars:
        # Truncate but keep the structure
        full = full[:max_chars] + '\n... [transcript truncated]'
    return full


SYSTEM_PROMPT = """\
Je bent een assistent die tijdstempels zoekt in transcripten van een theologische podcast.
Geef je antwoord als ALLEEN valide JSON — geen markdown, geen uitleg.
"""

USER_PROMPT_TEMPLATE = """\
Hieronder vind je een transcript van een podcastaflevering met tijdstempels in het formaat [MM:SS],
gevolgd door een lijst bijbelverwijzingen die in deze aflevering voorkomen.

Voor elke bijbelverwijzing wil ik het tijdstempel (in seconden) waarop deze verwijzing voor het eerst
inhoudelijk wordt aangehaald of besproken. Zoek het eerste segment in het transcript waar de betreffende
bijbeltekst ter sprake komt (bijv. het vers of hoofdstuk wordt geciteerd, besproken, of expliciet benoemd).

Afleveringsbeschrijving:
{description}

Transcript:
{transcript}

Bijbelverwijzingen om te lokaliseren:
{refs_json}

Geef je antwoord als JSON-array met dezelfde volgorde als de invoer, elk object met:
- "ref": de originele verwijzingstekst (kopieer exact)
- "start_seconds": het tijdstempel in seconden (integer), of null als de verwijzing niet te lokaliseren is

Voorbeeld: [{{"ref": "Johannes 3:16", "start_seconds": 754}}, {{"ref": "Genesis 1", "start_seconds": null}}]
"""


def find_start_seconds(client, description, transcript_text, refs):
    """Call Haiku 5.5 to find start_seconds for a list of bible refs."""
    refs_simple = [{'ref': r['ref'], 'note': r.get('note', '')} for r in refs]
    prompt = USER_PROMPT_TEMPLATE.format(
        description=description[:1500],
        transcript=transcript_text,
        refs_json=json.dumps(refs_simple, ensure_ascii=False, indent=2),
    )
    response = client.messages.create(
        model='claude-haiku-5-5',
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': prompt}],
    )
    # Find the first text block (skip ThinkingBlock etc.)
    raw = next((b.text for b in response.content if hasattr(b, 'text')), '').strip()
    # Strip markdown fences if present
    raw = re.sub(r'^```[a-z]*\n?', '', raw)
    raw = re.sub(r'\n?```$', '', raw)
    result = json.loads(raw)
    return result


def process_file(client, analysis_path, transcript_path, dry_run=False):
    """Process one analysis file. Returns (n_updated, n_null, refs_missing) tuple."""
    an = json.loads(analysis_path.read_text(encoding='utf-8'))
    refs = an.get('bible_refs', [])
    # Only process refs that are missing start_seconds
    to_fill = [r for r in refs if r.get('start_seconds') is None]
    if not to_fill:
        return 0, 0, []

    trans = json.loads(transcript_path.read_text(encoding='utf-8'))
    segments = trans.get('segments', [])
    transcript_text = format_transcript_for_prompt(segments)
    description = an.get('summary_tldr', '') or ''

    try:
        result = find_start_seconds(client, description, transcript_text, to_fill)
    except Exception as e:
        print(f'  ERROR calling API: {e}')
        return 0, 0, [r['ref'] for r in to_fill]

    # Map result back by ref text
    result_map = {}
    for item in result:
        if isinstance(item, dict) and item.get('ref'):
            result_map[item['ref']] = item.get('start_seconds')

    n_updated = 0
    n_null = 0
    still_missing = []
    for r in refs:
        if r.get('start_seconds') is not None:
            continue
        ref_text = r.get('ref', '')
        ss = result_map.get(ref_text)
        if ss is not None and isinstance(ss, (int, float)):
            r['start_seconds'] = int(ss)
            n_updated += 1
        else:
            n_null += 1
            still_missing.append(ref_text)

    if not dry_run and n_updated > 0:
        analysis_path.write_text(
            json.dumps(an, ensure_ascii=False, indent=2), encoding='utf-8')

    return n_updated, n_null, still_missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true',
                        help='Do not write files, just report what would change.')
    parser.add_argument('--episode', type=str, default=None,
                        help='Process only this episode key (e.g. 50 or x133821).')
    parser.add_argument('--api-key', type=str, default=None,
                        help='Anthropic API key (default: ANTHROPIC_API_KEY or CLAUDE_API_KEY env var).')
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('CLAUDE_API_KEY')
    if not api_key:
        sys.exit(
            'No API key found. Set ANTHROPIC_API_KEY env var or pass --api-key KEY.\n'
            'Get a key at https://console.anthropic.com/'
        )
    client = anthropic.Anthropic(api_key=api_key)

    if args.episode:
        keys = [args.episode]
    else:
        # All analysis files that have bible_refs without start_seconds
        keys = []
        for f in sorted(ANALYSIS_DIR.glob('*.json'),
                        key=lambda x: (not x.stem.isdigit(), int(x.stem) if x.stem.isdigit() else x.stem)):
            try:
                an = json.loads(f.read_text(encoding='utf-8'))
                refs = an.get('bible_refs', [])
                if any(r.get('start_seconds') is None for r in refs):
                    keys.append(f.stem)
            except Exception:
                pass

    print(f'Processing {len(keys)} episode(s) with missing bible ref start_seconds...')

    total_updated = 0
    total_null = 0
    all_missing = []

    for key in keys:
        a_path = ANALYSIS_DIR / f'{key}.json'
        t_path = TRANSCRIPT_DIR / f'{key}.json'
        if not a_path.exists():
            print(f'  [{key}] analysis file not found, skipping')
            continue
        if not t_path.exists():
            print(f'  [{key}] no transcript, skipping')
            refs = json.loads(a_path.read_text(encoding='utf-8')).get('bible_refs', [])
            missing = [r['ref'] for r in refs if r.get('start_seconds') is None]
            all_missing.extend(f'{key}: {r}' for r in missing)
            total_null += len(missing)
            continue

        print(f'  [{key}] ', end='', flush=True)
        n_up, n_null, missing = process_file(client, a_path, t_path, dry_run=args.dry_run)
        print(f'{n_up} updated, {n_null} could not locate')
        if missing:
            for m in missing:
                all_missing.append(f'{key}: {m}')
        total_updated += n_up
        total_null += n_null
        # Small delay to avoid rate limiting
        time.sleep(0.3)

    print()
    print(f'Done. Updated: {total_updated}, Could not locate: {total_null}')
    if all_missing:
        print(f'\nRefs without start_seconds ({len(all_missing)}):')
        for m in all_missing:
            print(f'  - {m}')
    else:
        print('All bible refs now have start_seconds.')


if __name__ == '__main__':
    main()
