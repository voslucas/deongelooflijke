"""The metadata sequence must preserve UTF-8 under Windows legacy defaults."""
import json
import pathlib
import shutil
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_guest_and_episode_builds_use_explicit_utf8(tmp_path):
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    intermediate = tmp_path / 'data' / 'intermediate'
    intermediate.mkdir(parents=True)
    episode = {
        'n': 328, 'title': '#328 Zoë Jansen', 't': 'Zoë Jansen',
        'date': '2026-11-24', 'secs': 60,
        'desc': 'Zoë Jansen is theoloog. Zij bespreekt “geloof” met Stefan Paas.',
        'rel': [], 'npo': '123', 'slug': 'zoe-jansen',
        'mp3': 'https://example.com/audio.mp3',
    }
    (intermediate / 'raw.json').write_text(
        json.dumps([episode], ensure_ascii=False), encoding='utf-8')
    for name in ('2_extract_guests.py', '3_build_episode_data.py'):
        script = scripts / name
        shutil.copyfile(ROOT / 'scripts' / name, script)
        # Disable Python's UTF-8 mode and fail on implicit text-file encodings,
        # even on systems where the native encoding is already UTF-8.
        result = subprocess.run(
            [sys.executable, '-X', 'utf8=0', '-X', 'warn_default_encoding=1',
             '-W', 'error::EncodingWarning', str(script)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    extracted = json.loads((intermediate / 'eps1.json').read_text(encoding='utf-8'))[0]
    built = json.loads((tmp_path / 'data' / 'episodes.json').read_text(encoding='utf-8'))['eps'][0]
    assert extracted['desc'] == episode['desc']
    assert built['x'] == episode['desc']
    assert built['g'] == ['Zoë Jansen']
    assert built['p'] is True
    assert built['n'] == 328
