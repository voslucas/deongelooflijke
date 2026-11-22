"""Build a transcript-based word-frequency index for all episodes.

Processes every transcript in data/transcripts/, extracts NOUN and PROPN
tokens via spaCy's Dutch model (lemmatized, lowercased), and writes the top-N
per episode to data/word_index.json.

The site's drawWords() fetches that file once and replaces the title/description
word counts with the richer transcript-derived ones.

Usage
-----
    python scripts/9_build_word_index.py

Dependencies
------------
    pip install spacy
    python -m spacy download nl_core_news_sm   # ~13 MB, good accuracy
    # or: python -m spacy download nl_core_news_lg  (~560 MB, slightly better)

Flags
-----
    --rebuild   Ignore existing index; reprocess all transcripts.
    --dry-run   Parse one transcript and print the top words; don't write.
"""

import argparse, json, pathlib, re, sys, unicodedata
from collections import Counter

ROOT   = pathlib.Path(__file__).resolve().parent.parent
TX_DIR = ROOT / 'data' / 'transcripts'
OUT    = ROOT / 'data' / 'word_index.json'

TOP_N = 80  # words stored per episode in the index

# ---------------------------------------------------------------------------
# Extra stop-lemmas on top of spaCy's built-in is_stop list.
# These are either show-specific meta words, host/fixed-guest names that
# appear in every episode, or ultra-generic nouns that carry no topical signal.
# ---------------------------------------------------------------------------
EXTRA_STOP = {
    # Show / platform meta
    'podcast', 'aflevering', 'luister', 'eo', 'npo', 'uitzending',
    'seizoen', 'fragment', 'gesprek', 'gesprekken', 'programma',
    # Hosts (appear in every episode, not topically informative)
    'david', 'boogerd', 'stefan', 'paas',
    # Very high-frequency generic nouns with no topical signal
    'keer', 'jaar', 'deel', 'man', 'mens', 'mensen', 'ding', 'dingen',
    'kant', 'manier', 'reden', 'punt', 'einde', 'begin', 'moment', 'tijd',
    'stuk', 'soort', 'soorten', 'niveau', 'vorm', 'vormen', 'dag', 'week',
    'land', 'wereld', 'plaats', 'groep', 'groepen',
    # Transcript artefacts / filler sounds
    'ja', 'nee', 'nou', 'hè', 'eh', 'hmm', 'oké', 'okay', 'tja', 'hm',
    'uhm', 'mhm', 'uh', 'ah', 'oh',
    # Common Dutch fillers that spaCy sometimes tags NOUN
    'beetje', 'paar', 'iets', 'iemand',
    # Verb infinitives that double as nouns but carry no topical signal
    'geloven', 'weten', 'denken', 'zeggen', 'maken', 'hebben',
    'kunnen', 'willen', 'moeten', 'gaan', 'komen', 'staan', 'liggen',
    'kijken', 'horen', 'leven', 'doen', 'zijn',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    """Lower-case + strip diacritics (matches site's norm() function)."""
    s = unicodedata.normalize('NFD', s.lower())
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


def load_spacy():
    """Return a spaCy NLP pipeline with only the tagger enabled (fast)."""
    try:
        import spacy  # noqa: F401
    except ImportError:
        print(
            'ERROR: spaCy is not installed.\n'
            '  pip install spacy\n'
            '  python -m spacy download nl_core_news_sm',
            file=sys.stderr,
        )
        sys.exit(1)

    import spacy
    disable = ['parser', 'ner', 'senter']

    for model in ('nl_core_news_lg', 'nl_core_news_md', 'nl_core_news_sm'):
        try:
            nlp = spacy.load(model, disable=disable)
            # Transcripts run ~100 k chars; raise the limit to be safe
            nlp.max_length = 2_000_000
            print(f'Loaded spaCy model: {model}')
            return nlp
        except OSError:
            continue

    print(
        'ERROR: no Dutch spaCy model found.\n'
        '  python -m spacy download nl_core_news_sm',
        file=sys.stderr,
    )
    sys.exit(1)


def read_transcript(path: pathlib.Path) -> str:
    """Return full transcript text from segment list (handles UTF-8 BOM)."""
    d = json.loads(path.read_text(encoding='utf-8-sig'))
    return ' '.join(s['text'] for s in d.get('segments', []) if s.get('text'))


def extract_counts(nlp, text: str) -> Counter:
    """Return {lemma: count} for NOUN/PROPN tokens in *text*."""
    doc = nlp(text)
    counts: Counter = Counter()
    for token in doc:
        if token.pos_ not in ('NOUN', 'PROPN'):
            continue
        if token.is_stop:
            continue
        lemma = _norm(token.lemma_)
        if len(lemma) < 3:
            continue
        if lemma in EXTRA_STOP:
            continue
        # Skip purely numeric / hyphen-only tokens
        if re.fullmatch(r'[\d\-]+', lemma):
            continue
        counts[lemma] += 1
    return counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rebuild',  action='store_true',
                        help='Ignore existing index; reprocess all transcripts.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Parse one transcript and print top words; skip writing.')
    parser.add_argument('--episode', help='Index only this episode, preserving other entries')
    args = parser.parse_args()

    nlp = load_spacy()

    existing: dict = {}
    if (not args.rebuild or args.episode) and OUT.exists():
        existing = json.loads(OUT.read_text(encoding='utf-8'))
        print(f'Loaded existing index: {len(existing)} episodes cached')

    files = sorted(TX_DIR.glob('*.json'))
    if args.episode:
        files = [f for f in files if f.stem == args.episode]
        if args.rebuild:
            existing.pop(args.episode, None)
    if not files:
        print(f'No transcript files found in {TX_DIR}')
        return

    print(f'Found {len(files)} transcript(s).  '
          f'{len(existing)} already in index → '
          f'{len(files) - sum(1 for f in files if f.stem in existing)} to process.')

    if args.dry_run:
        f = files[0]
        print(f'\nDry-run on {f.name}:')
        text = read_transcript(f)
        counts = extract_counts(nlp, text)
        print(f'  {len(counts)} unique content words')
        for w, n in counts.most_common(30):
            print(f'    {w}: {n}')
        return

    index = dict(existing)
    new_count = 0
    errors = []

    for i, f in enumerate(files, 1):
        key = f.stem
        if key in existing:
            continue

        try:
            text = read_transcript(f)
            if not text.strip():
                print(f'  [{i}/{len(files)}] {key}: empty transcript, skipping')
                continue

            counts = extract_counts(nlp, text)
            index[key] = dict(counts.most_common(TOP_N))
            new_count += 1

            status = f'  [{i}/{len(files)}] {key}: {len(counts)} words → top {len(index[key])} stored'
            if new_count % 20 == 0:
                # Save incrementally every 20 episodes so a crash doesn't lose work
                OUT.write_text(
                    json.dumps(index, ensure_ascii=False, separators=(',', ':')),
                    encoding='utf-8',
                )
                status += '  (saved)'
            print(status)

        except Exception as exc:
            print(f'  [{i}/{len(files)}] {key}: ERROR — {exc}')
            errors.append(key)

    # Final write
    OUT.write_text(
        json.dumps(index, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8',
    )
    size_kb = OUT.stat().st_size / 1024
    print(f'\nDone.  {new_count} new episode(s) processed.  '
          f'Total in index: {len(index)}  |  {size_kb:.0f} KB → {OUT}')
    if errors:
        sys.exit(1)


if __name__ == '__main__':
    main()
