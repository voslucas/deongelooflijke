"""Run the daily episode pipeline locally or in Actions, resuming unfinished stages.

Fetch and parse the feed (scripts fetch_feed, 1, 2, 3) before invoking this script.
Legacy episodes with both transcript and analysis are left alone. A processing
record is created for new work so partial enrichment is retried on later runs.
"""
import argparse
import datetime
import json
import os
import pathlib
import subprocess
import sys

from utils import ep_key

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATUS_DIR = ROOT / 'data/processing'


def read_json(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def pending_episodes(root=ROOT):
    settings = read_json(root / 'data/pipeline-settings.json', {})
    held = set(settings.get('held_episodes', []))
    episodes = read_json(root / 'data/episodes.json')['eps']
    pending = []
    for ep in sorted(episodes, key=lambda e: (e.get('d', ''), ep_key(e))):
        key = ep_key(ep)
        if key in held:
            continue
        status = read_json(root / f'data/processing/{key}.json', {})
        missing = any(not (root / f'data/{kind}/{key}.json').exists()
                      for kind in ('transcripts', 'analysis'))
        if missing or (status and not status.get('complete')):
            pending.append(key)
    return pending


def run(script, *args):
    command = [sys.executable, str(ROOT / 'scripts' / script), *args]
    print(f'→ {script} {" ".join(args)}', flush=True)
    subprocess.run(command, cwd=ROOT, check=True,
                   env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONUNBUFFERED': '1'})


def process_episode(key):
    status_path = STATUS_DIR / f'{key}.json'
    status = read_json(status_path, {'episode': key, 'steps': {}, 'complete': False})
    status['complete'] = False
    status.pop('error', None)

    def save():
        STATUS_DIR.mkdir(parents=True, exist_ok=True)
        status['updated'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        temp = status_path.with_suffix('.tmp')
        temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(status_path)

    def step(name, action):
        if status['steps'].get(name):
            return
        action()
        status['steps'][name] = True
        save()

    save()
    transcript = ROOT / f'data/transcripts/{key}.json'
    analysis = ROOT / f'data/analysis/{key}.json'

    def transcribe():
        if not transcript.exists():
            run('transcribe_azure.py', '--episode', key)
        if not transcript.exists():
            raise RuntimeError(f'Transcription did not produce episode {key}')

    def identify():
        try:
            run('identify_speakers.py', '--episode', key, '--apply')
        except subprocess.CalledProcessError:
            status['speaker_warning'] = 'Voice identification failed; initial speaker names retained'
            print(status['speaker_warning'], flush=True)

    def analyse():
        if not analysis.exists():
            run('analyze_episode.py', '--episode', key)
        if not analysis.exists():
            raise RuntimeError(f'Analysis did not produce episode {key}')
        if read_json(analysis).get('similar_status') == 'failed':
            run('analyze_episode.py', '--episode', key, '--similar-only')

    def index_words():
        run('9_build_word_index.py', '--episode', key)
        if key not in read_json(ROOT / 'data/word_index.json', {}):
            raise RuntimeError(f'Word index missing episode {key}')

    try:
        step('transcript', transcribe)
        step('speakers', identify)
        step('analysis', analyse)
        step('wikipedia', lambda: run('8_enrich_people_wiki.py', '--episode', key))
        step('book_details', lambda: run('9_enrich_books_detail.py', '--episode', key))
        step('guest_bios', lambda: run('enrich_guest_bios.py', '--episode', key))
        step('word_statistics', index_words)
        step('mentioned_persons', lambda: run('10_collect_persons.py'))
        status['complete'] = True
        status.pop('error', None)
        save()
        # Identification needs the audio; delete only once all stages succeed.
        (ROOT / f'data/mp3/{key}.mp3').unlink(missing_ok=True)
    except Exception as exc:
        status['error'] = str(exc)
        save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--episode', help='Process one episode (held episodes are refused)')
    group.add_argument('--all-pending', action='store_true')
    group.add_argument('--plan', action='store_true', help='List pending keys without changing anything')
    args = parser.parse_args()
    held = read_json(ROOT / 'data/pipeline-settings.json', {}).get('held_episodes', [])
    if args.episode in held:
        parser.error(f'Episode {args.episode} is held in data/pipeline-settings.json')
    keys = [args.episode] if args.episode else pending_episodes()
    known = {ep_key(ep) for ep in read_json(ROOT / 'data/episodes.json')['eps']}
    if args.episode and args.episode not in known:
        parser.error(f'Episode {args.episode} not found in data/episodes.json')
    print(f'Pending episodes: {", ".join(keys) or "none"}', flush=True)
    if args.plan:
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
                output.write(f'has_pending={str(bool(keys)).lower()}\n')
        return
    for key in keys:
        process_episode(key)


if __name__ == '__main__':
    main()
