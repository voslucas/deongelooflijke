"""Download and validate the public NPO feed before replacing the local snapshot."""
import argparse
import pathlib
from xml.etree import ElementTree as ET

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
FEED_URL = 'https://podcast.npo.nl/feed/de-ongelooflijke-podcast.xml'


def fetch_feed(destination: pathlib.Path, url: str = FEED_URL) -> int:
    response = requests.get(url, timeout=60, headers={
        'User-Agent': 'OngelooflijkArchief/1.0 (podcast archive)',
    })
    response.raise_for_status()
    tree = ET.fromstring(response.content)
    items = tree.findall('./channel/item')
    if not items or 'De Ongelooflijke' not in (tree.findtext('./channel/title') or ''):
        raise ValueError('Response is not the expected podcast RSS feed')
    if not all(item.find('enclosure') is not None for item in items):
        raise ValueError('Feed contains an episode without an audio enclosure')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.xml.tmp')
    temporary.write_bytes(response.content)
    temporary.replace(destination)
    return len(items)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path, default=ROOT / 'data/raw/feed.xml')
    args = parser.parse_args()
    print(f'Downloaded {fetch_feed(args.output)} episodes from {FEED_URL}')


if __name__ == '__main__':
    main()
