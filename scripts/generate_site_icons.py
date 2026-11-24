"""Regenerate browser/home-screen icons from the original, uncropped artwork.

Run: python scripts/generate_site_icons.py
Generated files are versioned; normal site builds only copy them.
"""
import json
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'design-system/assets/icons'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tokens = json.loads((ROOT / 'design-system/tokens.json').read_text(encoding='utf-8'))
    colors = {token['name']: token['value']['light'] for token in tokens['color']['tokens']}
    with Image.open(ROOT / 'design-system/assets/logos/logo360.jpg') as source:
        logo = ImageOps.exif_transpose(source).convert('RGB')

    def icon(size, padded=False):
        # A square of side 56% fits wholly inside the maskable 80% safe circle.
        side = round(size * .56) if padded else size
        artwork = ImageOps.contain(logo, (side, side), Image.Resampling.LANCZOS)
        canvas = Image.new('RGB', (size, size), colors['gold'])
        canvas.paste(artwork, ((size - artwork.width) // 2, (size - artwork.height) // 2))
        return canvas

    icon(64).save(OUT / 'favicon.ico', sizes=[(s, s) for s in (16, 32, 48, 64)])
    for size in (16, 32, 48, 96):
        icon(size).save(OUT / f'favicon-{size}x{size}.png', optimize=True)
    for size in (120, 152, 167, 180):
        name = 'apple-touch-icon.png' if size == 180 else f'apple-touch-icon-{size}x{size}.png'
        icon(size).save(OUT / name, optimize=True)
    icons = []
    for purpose in ('any', 'maskable'):
        for size in (192, 512):
            name = f'icon-{size}x{size}{"-maskable" if purpose == "maskable" else ""}.png'
            icon(size, purpose == 'maskable').save(OUT / name, optimize=True)
            icons.append({'src': name, 'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': purpose})
    manifest = {
        'id': './', 'name': 'Ongelooflijk Archief', 'short_name': 'Ongelooflijk',
        'description': 'Het onofficiële archief van De Ongelooflijke Podcast.',
        'lang': 'nl', 'start_url': './', 'scope': './', 'display': 'standalone',
        'background_color': colors['parchment'], 'theme_color': colors['parchment'],
        'icons': icons,
    }
    (OUT / 'site.webmanifest').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for size in (144, 150, 310):
        icon(size, padded=True).save(OUT / f'mstile-{size}x{size}.png', optimize=True)
    (OUT / 'browserconfig.xml').write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<browserconfig><msapplication><tile>'
        '<square150x150logo src="mstile-150x150.png"/>'
        '<square310x310logo src="mstile-310x310.png"/>'
        f'<TileColor>{colors["gold"]}</TileColor>'
        '</tile></msapplication></browserconfig>\n', encoding='utf-8')
    print(f'Generated icons in {OUT}')


if __name__ == '__main__':
    main()
