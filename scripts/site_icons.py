"""Shared icon metadata and publishing for both site builders."""
import pathlib
import shutil
import json
from functools import lru_cache


@lru_cache(maxsize=1)
def _colors():
    tokens = json.loads((pathlib.Path(__file__).resolve().parents[1] /
                         'design-system/tokens.json').read_text(encoding='utf-8'))
    return {token['name']: token['value'] for token in tokens['color']['tokens']}


def icon_head(prefix='/'):
    """Use root URLs for static routes and relative URLs for the legacy shell."""
    return '\n'.join([
        *[f'<meta name="theme-color" content="{_colors()["parchment"][theme]}" media="(prefers-color-scheme: {theme})">'
          for theme in ('light', 'dark')],
        f'<link rel="icon" href="{prefix}favicon.ico" sizes="16x16 32x32 48x48 64x64">',
        *[f'<link rel="icon" type="image/png" sizes="{size}x{size}" href="{prefix}favicon-{size}x{size}.png">'
          for size in (16, 32, 48, 96)],
        *[f'<link rel="apple-touch-icon" sizes="{size}x{size}" href="{prefix}{filename}">'
          for size, filename in [(120, 'apple-touch-icon-120x120.png'),
                                 (152, 'apple-touch-icon-152x152.png'),
                                 (167, 'apple-touch-icon-167x167.png'),
                                 (180, 'apple-touch-icon.png')]],
        f'<link rel="manifest" href="{prefix}site.webmanifest">',
        '<meta name="application-name" content="Ongelooflijk Archief">',
        '<meta name="apple-mobile-web-app-title" content="Ongelooflijk Archief">',
        f'<meta name="msapplication-config" content="{prefix}browserconfig.xml">',
        f'<meta name="msapplication-TileImage" content="{prefix}mstile-144x144.png">',
        f'<meta name="msapplication-TileColor" content="{_colors()["gold"]["light"]}">',
    ]) + '\n'


def publish_icons(root: pathlib.Path, out: pathlib.Path):
    shutil.copytree(root / 'design-system/assets/icons', out, dirs_exist_ok=True)
