"""Prefetch selected Wikipedia portraits for both site builders.

Run directly to warm data/person_images/. --offline forbids downloads;
--retry-missing bypasses the 24-hour failure cooldown.
"""
import argparse
import hashlib
import io
import json
import pathlib
import re
import shutil
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageOps

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_BYTES = 8 * 1024 * 1024
RETRY_SECONDS = 24 * 3600


def image_key(url):
    if not isinstance(url, str):
        return ''
    if url.startswith('//'):
        url = 'https:' + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ('https', 'http') or not parts.netloc:
        return ''
    path = parts.path
    if parts.hostname in ('thumb.wikimedia.org', 'upload.wikimedia.org') and '/thumb/' in path:
        path = re.sub(r'/\d+px-', '/250px-', path)
    return urllib.parse.urlunsplit(('https', parts.netloc, path, parts.query, ''))


def collect_images(root):
    urls = set()
    # Only selected matches, never unverified candidates in wiki_cache.json.
    for directory in ('analysis', 'persons_mentioned'):
        for path in sorted((root / 'data' / directory).glob('*.json')):
            data = json.loads(path.read_text(encoding='utf-8'))
            people = data.get('people', []) if directory == 'analysis' else [data]
            urls.update(filter(None, (image_key(p.get('wiki_image')) for p in people)))
    return sorted(urls)


def download_image(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'OngelooflijkArchief/1.0 (https://github.com/deongelooflijke; portrait cache)',
        'Accept': 'image/*',
    })
    with urllib.request.urlopen(request, timeout=12) as response:
        if not response.headers.get('Content-Type', '').lower().startswith('image/'):
            raise ValueError('not an image response')
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError('portrait exceeds download limit')
    return payload


def normalize_image(payload):
    with Image.open(io.BytesIO(payload)) as original:
        original.verify()
    with Image.open(io.BytesIO(payload)) as original:
        if min(original.size) < 32:
            raise ValueError('portrait is a tiny placeholder')
        image = ImageOps.exif_transpose(original).convert('RGBA')
        background = Image.new('RGB', image.size, 'white')
        background.paste(image, mask=image.getchannel('A'))
        background.thumbnail((320, 320))
        output = io.BytesIO()
        background.save(output, 'JPEG', quality=85, optimize=True)
        return output.getvalue()


def prepare_person_images(root=ROOT, output=None, offline=False, retry_missing=False):
    cache = root / 'data/person_images'
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / 'index.json'
    try:
        previous = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        previous = {}
    now = time.time()

    def process(url):
        old = previous.get(url, {})
        filename = old.get('file', '')
        if filename and pathlib.Path(filename).name == filename:
            try:
                normalize_image((cache / filename).read_bytes())
                return url, old, 'cached'
            except Exception:
                pass
        if offline:
            # Retain failure timestamps so an offline build cannot reset cooldowns.
            return url, {'failed_at': old['failed_at']} if old.get('failed_at') else {}, 'unavailable'
        if not retry_missing and now - old.get('failed_at', 0) < RETRY_SECONDS:
            return url, old, 'unavailable'
        try:
            payload = normalize_image(download_image(url))
            filename = hashlib.sha256(url.encode()).hexdigest()[:24] + '.jpg'
            path = cache / filename
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(payload)
            temporary.replace(path)
            return url, {'file': filename, 'source_url': url}, 'downloaded'
        except Exception as exc:
            print(f'  Portrait unavailable: {url}: {exc}', flush=True)
            return url, {'failed_at': now}, 'unavailable'

    manifest, counts = {}, dict(cached=0, downloaded=0, unavailable=0)
    with ThreadPoolExecutor(max_workers=2) as executor:
        for url, entry, status in executor.map(process, collect_images(root)):
            manifest[url] = entry
            counts[status] += 1
    temporary = manifest_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(manifest_path)
    urls = {}
    if output is not None:
        destination = output / 'data/person_images'
        destination.mkdir(parents=True, exist_ok=True)
        for entry in manifest.values():
            if entry.get('file'):
                shutil.copy2(cache / entry['file'], destination / entry['file'])
        urls = {url: '/data/person_images/' + entry['file']
                for url, entry in manifest.items() if entry.get('file')}
    print('  Person images: ' + ', '.join(f'{v} {k}' for k, v in counts.items()), flush=True)
    return urls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--retry-missing', action='store_true')
    args = parser.parse_args()
    prepare_person_images(offline=args.offline, retry_missing=args.retry_missing)


if __name__ == '__main__':
    main()
