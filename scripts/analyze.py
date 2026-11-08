"""Enrich a transcript with summary, chapters, highlights, mentions and bible refs.

Usage:
    python scripts/analyze.py --episode N [--force] [--api-key KEY]
    python scripts/analyze.py --all-missing [--force] [--api-key KEY]

Dependencies:
    pip install anthropic

API key: set CLAUDE_API_KEY or ANTHROPIC_API_KEY in .env or the environment.
Input/output: data/transcripts/{n}.json  (modified in place)
"""
import argparse, json, os, pathlib, sys
if sys.stdout.encoding and sys.stdout.encoding.lower().startswith('cp'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = pathlib.Path(__file__).resolve().parent.parent
EPISODES_JSON = ROOT / 'data' / 'episodes.json'
TRANSCRIPTS_DIR = ROOT / 'data' / 'transcripts'

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None


def _load_api_key(explicit=None):
    if explicit:
        return explicit
    for name in ('ANTHROPIC_API_KEY', 'CLAUDE_API_KEY'):
        k = os.environ.get(name)
        if k:
            return k
    env_file = ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8').splitlines():
            for prefix in ('ANTHROPIC_API_KEY=', 'CLAUDE_API_KEY='):
                if line.startswith(prefix):
                    return line[len(prefix):].strip().strip('"\'')
    return None


def _fmt_time(seconds):
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m}:{s:02d}'


def _build_transcript_text(transcript):
    """Format segments as [MM:SS] SpeakerName: text lines."""
    id_to_name = {s['id']: s['name'] for s in transcript.get('speakers', [])}
    lines = []
    for seg in transcript.get('segments', []):
        t = _fmt_time(seg['start'])
        name = id_to_name.get(seg['speaker'], seg['speaker'])
        lines.append(f'[{t}] {name}: {seg["text"]}')
    return '\n'.join(lines)


ENRICH_TOOL = {
    'name': 'enrich_transcript',
    'description': (
        'Analyseer het transcript van een aflevering van De Ongelooflijke Podcast en '
        'geef een gestructureerde verrijking terug in het Nederlands.'
    ),
    'input_schema': {
        'type': 'object',
        'required': ['summary', 'chapters', 'highlights', 'mentions', 'bible'],
        'properties': {
            'summary': {
                'type': 'object',
                'required': ['tldr', 'points'],
                'properties': {
                    'tldr': {
                        'type': 'string',
                        'description': 'Één zin die de essentie van het gesprek samenvat.',
                    },
                    'points': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': '3 tot 5 bullet points met de hoofdpunten.',
                    },
                },
            },
            'chapters': {
                'type': 'array',
                'description': '4 tot 8 inhoudelijke secties. start is tijdstempel in seconden.',
                'items': {
                    'type': 'object',
                    'required': ['start', 'title', 'summary'],
                    'properties': {
                        'start': {'type': 'number', 'description': 'Tijdstempel in seconden.'},
                        'title': {'type': 'string', 'description': 'Korte Nederlandse titel (max 7 woorden).'},
                        'summary': {'type': 'string', 'description': 'Één à twee zinnen samenvatting.'},
                    },
                },
            },
            'highlights': {
                'type': 'array',
                'description': '3 tot 5 memorabele citaten of momenten.',
                'items': {
                    'type': 'object',
                    'required': ['t', 'kind', 'speaker', 'text'],
                    'properties': {
                        't': {'type': 'number', 'description': 'Tijdstempel in seconden.'},
                        'kind': {
                            'type': 'string',
                            'enum': ['Uitspraak', 'Keerpunt', 'Inzicht', 'Vraag', 'Conclusie'],
                        },
                        'speaker': {'type': 'string', 'description': 'Speaker-ID (S1, S2, …).'},
                        'text': {'type': 'string', 'description': 'De letterlijke uitspraak of beschrijving.'},
                    },
                },
            },
            'mentions': {
                'type': 'array',
                'description': (
                    'Personen, filosofen, boeken en plaatsen die ter sprake komen. '
                    'Één vermelding per naam (eerste tijdstempel). '
                    'Noem niet de vaste sprekers David Boogerd en Stefan Paas zelf.'
                ),
                'items': {
                    'type': 'object',
                    'required': ['name', 'type', 't', 'speaker'],
                    'properties': {
                        'name': {'type': 'string', 'description': 'Canonieke naam, bijv. "Søren Kierkegaard".'},
                        'type': {
                            'type': 'string',
                            'enum': ['persoon', 'filosoof', 'boek', 'plaats'],
                            'description': (
                                'persoon = historische of publieke figuur; '
                                'filosoof = specifiek filosoof of theoloog; '
                                'boek = publicatie of werk; '
                                'plaats = geografische locatie.'
                            ),
                        },
                        't': {'type': 'number', 'description': 'Tijdstempel van eerste vermelding in seconden.'},
                        'speaker': {'type': 'string', 'description': 'Speaker-ID die de naam noemt.'},
                    },
                },
            },
            'bible': {
                'type': 'array',
                'description': 'Concrete Bijbelpassages die worden aangehaald of besproken.',
                'items': {
                    'type': 'object',
                    'required': ['ref', 't', 'speaker'],
                    'properties': {
                        'ref': {'type': 'string', 'description': 'Referentie, bijv. "Lucas 15" of "Johannes 3:16".'},
                        't': {'type': 'number', 'description': 'Tijdstempel in seconden.'},
                        'speaker': {'type': 'string', 'description': 'Speaker-ID.'},
                    },
                },
            },
        },
    },
}

SYSTEM_PROMPT = (
    'Je bent een assistent die afleveringen van De Ongelooflijke Podcast analyseert. '
    'De podcast is een Nederlands gesprek over geloof, theologie, filosofie en samenleving. '
    'Presentator is David Boogerd (journalist); Stefan Paas is de vaste gast '
    '(theoloog, hoogleraar Vrije Universiteit Amsterdam). '
    'Gasten zijn schrijvers, wetenschappers, politici of andere publieke figuren.\n\n'
    'Analyseer het transcript zorgvuldig en roep de functie enrich_transcript aan met je bevindingen. '
    'Schrijf alle tekst in het Nederlands. Gebruik de tijdstempels uit het transcript.'
)


def enrich_episode(transcript, episode_meta, api_key):
    """Call Claude Opus to fill summary/chapters/highlights/mentions/bible."""
    if _anthropic is None:
        sys.exit('anthropic package not installed. Run: pip install anthropic')

    client = _anthropic.Anthropic(api_key=api_key)

    speakers_desc = ', '.join(
        f"{s['name']} ({s['role']})" for s in transcript.get('speakers', [])
    )
    tx_text = _build_transcript_text(transcript)
    title = episode_meta.get('t', '')
    description = episode_meta.get('x', '') or episode_meta.get('xs', '')

    user_content = (
        f'Aflevering: {title}\n'
        f'Sprekers: {speakers_desc}\n'
        f'Beschrijving: {description}\n\n'
        f'TRANSCRIPT:\n{tx_text}'
    )

    print(f'  Sending {len(tx_text.split())} words to Claude …')
    with client.messages.stream(
        model='claude-opus-5-5',
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': user_content}],
        tools=[ENRICH_TOOL],
        output_config={'effort': 'high'},
    ) as stream:
        response = stream.get_final_message()

    for block in response.content:
        if block.type == 'tool_use' and block.name == 'enrich_transcript':
            return block.input

    raise RuntimeError(
        f'Claude did not call enrich_transcript '
        f'(stop_reason={response.stop_reason})'
    )


def main():
    parser = argparse.ArgumentParser(description='Enrich transcripts with Claude analysis')
    parser.add_argument('--episode', type=str, help='Episode number')
    parser.add_argument('--all-missing', action='store_true',
                        help='Enrich all transcripts whose summary is empty')
    parser.add_argument('--force', action='store_true',
                        help='Re-analyze even if summary already exists')
    parser.add_argument('--api-key', help='Anthropic / Claude API key')
    args = parser.parse_args()

    if not args.episode and not args.all_missing:
        parser.error('Provide --episode N or --all-missing')

    api_key = _load_api_key(args.api_key)
    if not api_key:
        sys.exit(
            'No API key found. Set CLAUDE_API_KEY or ANTHROPIC_API_KEY in .env '
            'or pass --api-key.'
        )

    all_eps = json.loads(EPISODES_JSON.read_text(encoding='utf-8'))
    eps_by_key = {str(e['n']): e for e in all_eps['eps'] if e.get('n') is not None}

    if args.episode:
        keys = [str(args.episode)]
    else:
        keys = []
        for p in sorted(TRANSCRIPTS_DIR.glob('*.json')):
            tx = json.loads(p.read_text(encoding='utf-8'))
            if not tx.get('summary', {}).get('tldr'):
                keys.append(p.stem)
        print(f'{len(keys)} transcript(s) missing enrichment')

    for key in keys:
        tx_path = TRANSCRIPTS_DIR / f'{key}.json'
        if not tx_path.exists():
            print(f'  No transcript found: {key}')
            continue

        transcript = json.loads(tx_path.read_text(encoding='utf-8'))

        if not args.force and transcript.get('summary', {}).get('tldr'):
            print(f'  Episode {key} already enriched (--force to redo)')
            continue

        ep_meta = eps_by_key.get(key, {})
        print(f'Enriching #{key} — {ep_meta.get("t", "")[:60]}')

        try:
            result = enrich_episode(transcript, ep_meta, api_key)

            transcript['summary'] = result.get('summary', {'tldr': '', 'points': []})
            transcript['chapters'] = result.get('chapters', [])
            transcript['highlights'] = result.get('highlights', [])
            transcript['mentions'] = result.get('mentions', [])
            transcript['bible'] = result.get('bible', [])

            tx_path.write_text(
                json.dumps(transcript, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            print(
                f'  -> {tx_path.relative_to(ROOT)}  '
                f'({len(transcript["chapters"])} chapters, '
                f'{len(transcript["mentions"])} mentions, '
                f'{len(transcript["bible"])} bible refs)'
            )
        except Exception as exc:
            print(f'  Error enriching {key}: {exc}')


if __name__ == '__main__':
    main()
