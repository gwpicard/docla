from pathlib import Path

from docla.theme.loader import ThemeError, load_theme
from docla.theme.models import Theme, to_pt

NEUTRAL_ROOT = Path(__file__).resolve().parent.parent / "themes" / "neutral"

__all__ = ["Theme", "ThemeError", "load_theme", "neutral_theme", "to_pt"]


def neutral_theme() -> Theme:
    """Load the shipped neutral theme, the default until a brand is ingested."""
    return load_theme(NEUTRAL_ROOT)
