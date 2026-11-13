"""Resolve the theme for a working document."""

from pathlib import Path

from starlette.datastructures import State

from docla.brand.workspace import BRANDS_DIR, SLUG, default_root
from docla.model import Document
from docla.theme import Theme, ThemeError, load_theme


def brands_root(project: Path) -> Path:
    resolved = project.resolve()
    return next((path for path in (resolved, *resolved.parents) if path.name == BRANDS_DIR), default_root())


def document_theme(state: State, doc: Document) -> Theme:
    value = doc.front.get("theme")
    if value is None or value == "" or value == "neutral":
        return state.theme
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ThemeError(f"Invalid theme: {value!r}")
    folder = state.brands / value / "theme"
    if not folder.is_dir():
        raise ThemeError(f"Theme for {value!r} not found: {folder}")
    return load_theme(folder)
