"""Capture and compare component layout facts."""

import tempfile
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from docla.model import Document, Section
from docla.render.components import all_manifests
from docla.render.marks import ElementMark
from docla.render.swatch import swatch
from docla.theme import neutral_theme


def facts_for(name: str, fixtures_dir: Path) -> dict[str, Any]:
    """Render a section fixture and return its marks and words by role."""
    data = yaml.safe_load((Path(fixtures_dir) / f"{name}.yaml").read_text(encoding="utf-8"))
    section = Section.model_validate(data)
    manifests = all_manifests()
    manifest = manifests.get(section.component or name)
    fmt = manifest.format if manifest else "slides"
    doc = Document(front={}, format=fmt, sections=[section])
    if not section.id:
        raise ValueError(f"fixture {name!r} has no section id")
    with tempfile.TemporaryDirectory() as folder:
        facts = swatch(doc, section.id, Path(folder), neutral_theme()).facts
    result: dict[str, Any] = {}
    for mark in facts.marks:
        if isinstance(mark, ElementMark):
            role = result.setdefault(mark.role, {"marks": [], "words": []})
            role["marks"].append(
                {"page": mark.page, "x0": mark.x, "y0": mark.y, "x1": mark.x + mark.w, "y1": mark.y + mark.h}
            )
    for word in facts.words:
        if word.role is not None:
            role = result.setdefault(word.role, {"marks": [], "words": []})
            role["words"].append({**word.box.model_dump(), "text": word.text})
    return result


def _compare_boxes(role: str, kind: str, actual: list, golden: list, tolerance: float) -> list[str]:
    messages = []
    if len(actual) != len(golden):
        messages.append(f"{role}: {kind} count differs ({len(actual)} != {len(golden)})")
    for index, (a, g) in enumerate(zip(actual, golden, strict=False)):
        if (
            a.get("page") != g.get("page")
            or a.get("text") != g.get("text")
            or any(abs(a[key] - g[key]) > tolerance for key in ("x0", "y0", "x1", "y1"))
        ):
            messages.append(f"{role}: {kind} {index} differs")
    return messages


def compare_facts(actual: dict, golden: dict, tolerance: float = 0.5) -> list[str]:
    """Return differences in roles, counts, text and box positions."""
    messages = [
        f"{role}: role missing from {'actual' if role not in actual else 'golden'}"
        for role in sorted(actual.keys() ^ golden.keys())
    ]
    for role in sorted(actual.keys() & golden.keys()):
        for kind in ("marks", "words"):
            messages.extend(_compare_boxes(role, kind, actual[role][kind], golden[role][kind], tolerance))
    return messages
