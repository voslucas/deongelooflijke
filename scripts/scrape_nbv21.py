"""Scrape NBV21 verse text from nbv21.nl and save as per-book JSON files.

Usage:
    pip install playwright requests
    playwright install chromium
    python scripts/scrape_nbv21.py

Output: data/bible/{BOOK}.json  e.g. data/bible/MAT.json
Format: {"1": {"1": "In het begin…", "2": "…"}, …}

The site is JS-rendered so we need Playwright.  Chapters already saved on disk
are skipped so the script can be interrupted and resumed.  Rate-limit is 1 s
between requests to be polite.
"""
import asyncio
import json
import pathlib
import re
import time
import xml.etree.ElementTree as ET

import requests
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "bible"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SITEMAP_URL = "https://nbv21.nl/sitemap/bible-sitemap.xml"
BASE_URL = "https://nbv21.nl/bijbel/NBV21"

# JS snippet injected into each page to extract verse text
EXTRACT_JS = """
(() => {
    const map = {};
    document.querySelectorAll('.verse-span:not(.verse_footnote):not(.verse_bold)').forEach(el => {
        const rawRef = (el.getAttribute('rel') || '').trim();
        if (!rawRef) return;
        // rel may have trailing space, e.g. "GEN.1.1 "
        const ref = rawRef.trim();
        // skip verse number spans (they only contain the number)
        if (el.classList.contains('verse_number')) return;
        const texts = Array.from(el.querySelectorAll('.verse_text'))
            .map(s => s.innerText || s.textContent)
            .join('').trim();
        if (!texts) return;
        if (!map[ref]) map[ref] = '';
        map[ref] = (map[ref] + ' ' + texts).trim();
    });
    return JSON.stringify(map);
})()
"""


def get_chapter_urls() -> list[tuple[str, int]]:
    """Parse the sitemap and return list of (book_code, chapter_num) tuples."""
    resp = requests.get(SITEMAP_URL, timeout=30)
    resp.raise_for_status()
    # Namespace-aware parse
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(resp.text)
    urls = []
    pattern = re.compile(r"/bijbel/NBV21/([A-Z0-9]+)\.(\d+)/?$")
    for loc in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
        url = loc.text or ""
        m = pattern.search(url)
        if m:
            book = m.group(1)
            ch = int(m.group(2))
            urls.append((book, ch))
    return urls


def already_have(book: str, chapter: int) -> bool:
    """Return True if this chapter is already saved."""
    out_file = OUT_DIR / f"{book}.json"
    if not out_file.exists():
        return False
    try:
        data = json.loads(out_file.read_text(encoding="utf-8"))
        return str(chapter) in data
    except Exception:
        return False


def save_chapter(book: str, chapter: int, verse_map: dict[str, str]) -> None:
    """Merge extracted verses into data/bible/{BOOK}.json."""
    out_file = OUT_DIR / f"{book}.json"
    if out_file.exists():
        try:
            data = json.loads(out_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    ch_data: dict[str, str] = {}
    for ref, text in verse_map.items():
        # ref format: "GEN.1.1"
        parts = ref.split(".")
        if len(parts) == 3:
            v = parts[2].strip()
            ch_data[v] = text
    if ch_data:
        data[str(chapter)] = dict(sorted(ch_data.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999))
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=None, separators=(",", ":")), encoding="utf-8")


async def scrape_chapter(browser, book: str, chapter: int) -> dict[str, str]:
    """Load one chapter page and return {ref: text} mapping."""
    url = f"{BASE_URL}/{book}.{chapter}/"
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Wait for verse spans to appear
        try:
            await page.wait_for_selector(".verse-span", timeout=15000)
        except Exception:
            print(f"  WARNING: no .verse-span found on {url}")
            return {}
        raw = await page.evaluate(EXTRACT_JS)
        verse_map: dict[str, str] = json.loads(raw)
        return verse_map
    except Exception as exc:
        print(f"  ERROR scraping {url}: {exc}")
        return {}
    finally:
        await page.close()


async def main_async():
    print("Fetching sitemap…")
    chapters = get_chapter_urls()
    print(f"Found {len(chapters)} chapters in sitemap.")

    todo = [(b, c) for b, c in chapters if not already_have(b, c)]
    print(f"{len(todo)} chapters to scrape ({len(chapters) - len(todo)} already saved).")

    if not todo:
        print("Nothing to do.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for i, (book, chapter) in enumerate(todo):
            print(f"[{i+1}/{len(todo)}] {book}.{chapter}", end="  ", flush=True)
            verse_map = await scrape_chapter(browser, book, chapter)
            if verse_map:
                save_chapter(book, chapter, verse_map)
                print(f"({len(verse_map)} verses)")
            else:
                print("(no verses)")
            if i < len(todo) - 1:
                await asyncio.sleep(1)
        await browser.close()

    print("Done. Files written to data/bible/")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
