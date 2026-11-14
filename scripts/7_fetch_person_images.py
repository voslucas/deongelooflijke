"""Fetch profile images for persons that have a known Twitter or Bluesky handle.

Usage:
    python scripts/7_fetch_person_images.py

Reads:   data/persons/*.json
Outputs: data/persons/images/{slug}.jpg

Uses the free unavatar.io service (no API key required) to retrieve profile
images from Twitter/X and Bluesky.  An existing image is never overwritten —
place or replace images manually by dropping a file into data/persons/images/.

For LinkedIn photos (which unavatar.io does not cover): download the photo
manually from the profile page and save it as data/persons/images/{slug}.jpg.
"""
import json, pathlib, re, urllib.error, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
PERSONS_DIR = ROOT / 'data' / 'persons'
IMG_DIR = PERSONS_DIR / 'images'

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp')
HEADERS = {'User-Agent': 'ongelooflijk-archief/1.0'}


def extract_handle(url: str, platform: str) -> str | None:
    if platform == 'twitter':
        m = re.match(r'https?://(?:www\.)?(?:twitter|x)\.com/([^/?#]+)', url)
    elif platform == 'bluesky':
        m = re.match(r'https?://bsky\.app/profile/([^/?#]+)', url)
    else:
        return None
    return m.group(1) if m else None


def fetch_image(handle: str, platform: str) -> bytes | None:
    if platform == 'twitter':
        url = f'https://unavatar.io/twitter/{handle}'
    elif platform == 'bluesky':
        url = f'https://unavatar.io/{handle}'
    else:
        return None
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status == 200 and 'image' in r.headers.get('Content-Type', ''):
                return r.read()
    except (urllib.error.URLError, OSError) as exc:
        print(f'    fetch failed ({platform} @{handle}): {exc}')
    return None


def main() -> None:
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(PERSONS_DIR.glob('*.json'))
    if not files:
        print('No person JSON files found in data/persons/.')
        return

    fetched = skipped = no_handle = 0

    for f in files:
        k = f.stem
        # Skip if any supported image extension already exists
        if any((IMG_DIR / f'{k}{ext}').exists() for ext in IMAGE_EXTS):
            print(f'  {k}: image already exists, skipping')
            skipped += 1
            continue

        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except Exception as exc:
            print(f'  {k}: could not read JSON ({exc}), skipping')
            continue

        socials = data.get('socials', {})

        # Try Twitter first, then Bluesky
        for platform in ('twitter', 'bluesky'):
            url = socials.get(platform, '')
            if not url:
                continue
            handle = extract_handle(url, platform)
            if not handle:
                continue
            print(f'  {k}: fetching via {platform} @{handle} …', end='', flush=True)
            img_bytes = fetch_image(handle, platform)
            if img_bytes:
                out = IMG_DIR / f'{k}.jpg'
                out.write_bytes(img_bytes)
                print(f' → {len(img_bytes):,} bytes saved')
                fetched += 1
                break
        else:
            print(f'  {k}: no usable handle, skipping (add image manually)')
            no_handle += 1

    print(f'\nDone: {fetched} fetched, {skipped} already present, {no_handle} no handle.')
    print(f'To add an image manually: drop data/persons/images/{{slug}}.jpg')


if __name__ == '__main__':
    main()
