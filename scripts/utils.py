"""Shared utilities used across multiple pipeline scripts."""
import re, unicodedata


def slug(name: str) -> str:
    """Lower-case name → URL-safe slug, with accent stripping."""
    s = unicodedata.normalize('NFD', name.lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def name_from_slug(s: str) -> str:
    """Reverse a slug back to a Title Case name."""
    return s.replace('-', ' ').title()


def ep_key(e: dict) -> str:
    """Canonical string key for an episode dict (number or 'x<id>')."""
    return str(e['n']) if e['n'] is not None else 'x' + e['id']


def truncate_xs(text: str, max_chars: int = 320) -> str:
    """Truncate text at a word boundary; no mid-word cuts."""
    if not text:
        return ''
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(None, 1)[0]
    return cut if cut else text[:max_chars]
