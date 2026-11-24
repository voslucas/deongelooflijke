"""Enforce the editorial theme list at analysis and publication boundaries."""
import json
from pathlib import Path

THEMES_PATH = Path(__file__).resolve().parent.parent / 'data' / 'themes.json'


def validate_themes(values, *, context='themes') -> list[str]:
    """Reject unknown labels rather than silently publishing new categories."""
    labels = {theme['label'] for theme in json.loads(THEMES_PATH.read_text(encoding='utf-8'))}
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError(f'{context}: themes must be a list of exact labels from data/themes.json')
    unknown = [value for value in values if value not in labels]
    if unknown:
        raise ValueError(f'{context}: unknown theme labels {unknown!r}; use exact labels from data/themes.json')
    if len(values) > 4 or len(set(values)) != len(values):
        raise ValueError(f'{context}: choose at most four distinct theme labels')
    return values
