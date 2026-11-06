"""Plan an outline from gathered facts and prepare it for drafting."""

import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from docla.agents.client import Claude
from docla.agents.gatherer import Fact
from docla.agents.prompts import system_blocks
from docla.doctypes import Doctype, OutlineEntry
from docla.model import Document, Section
from docla.render.chooser import Chooser, default_path
from docla.render.compose import default_chooser
from docla.source.ids import IdStore, stamp
from docla.theme import Theme, neutral_theme


class OutlineLine(BaseModel):
    section: str | None = None
    title: str
    intent: str
    component: str
    facts: list[str] = Field(default_factory=list)
    gap: str | None = None


class Outline(BaseModel):
    lines: list[OutlineLine]
    questions: list[str] = Field(default_factory=list)


class OutlineRejected(ValueError):
    """The retry still contains intents the chooser cannot draw."""


def _outline_entries(entries: list[OutlineEntry]) -> list[str]:
    lines = []
    for entry in entries:
        lines.append(
            f"section: {entry.section}, intent: {entry.intent}, required: {entry.required}, repeat: {entry.repeat}"
        )
        lines.extend(_outline_entries(entry.children))
    return lines


def _prompt(facts: list[Fact], doctype: Doctype, allowed: list[str]) -> str:
    data = yaml.safe_load(default_path().read_text(encoding="utf-8"))
    descriptions = data.get("intents", {})
    lines = [f"Doctype: {doctype.name}", f"Format: {doctype.format}", f"Audience: {doctype.audience}", "Outline:"]
    lines.extend(_outline_entries(doctype.outline))
    lines.append("Allowed intents:")
    lines.extend(f"{intent}: {descriptions.get(intent, {}).get('describes', '')}" for intent in allowed)
    lines.append("Facts:")
    for index, fact in enumerate(facts, 1):
        source = f"{fact.source_key} {fact.locator}" if fact.locator is not None else fact.source_key
        lines.append(f"F{index} [{source}] {fact.text}")
    lines.append(
        "Ask at most two questions, only for what the material does not answer. "
        "Set gap on any line that needs a missing fact."
    )
    return "\n".join(lines)


async def plan(
    claude: Claude,
    facts: list[Fact],
    doctype: Doctype,
    brief: str,
    *,
    theme: Theme | None = None,
    chooser: Chooser | None = None,
) -> Outline:
    chooser = default_chooser() if chooser is None else chooser
    theme = neutral_theme() if theme is None else theme
    allowed = sorted({intent for intent, _ in chooser.entries if chooser.knows(intent, doctype.format)})
    system = system_blocks("planner", theme, brief)
    content = [{"type": "text", "text": _prompt(facts, doctype, allowed)}]
    result = await claude.call("planner", Outline, system=system, content=content, effort="medium")
    unknown = sorted({line.intent for line in result.lines} - set(allowed))
    if unknown:
        correction = f"Unknown intents: {', '.join(unknown)}. Allowed intents: {', '.join(allowed)}."
        result = await claude.call(
            "planner", Outline, system=system, content=[*content, {"type": "text", "text": correction}], effort="medium"
        )
        unknown = sorted({line.intent for line in result.lines} - set(allowed))
        if unknown:
            raise OutlineRejected(f"Unknown intents: {', '.join(unknown)}")
    result.questions = result.questions[:2]
    return result


def outline_to_document(outline: Outline, front: dict[str, Any], *, store: IdStore | None = None) -> Document:
    fmt = front.get("format")
    if fmt not in ("slides", "doc"):
        raise ValueError("front format must be slides or doc")
    sections = [
        Section(
            intent=line.intent,
            section=line.section,
            title=line.title,
            paragraphs=[f"[GAP: {line.gap}]"] if line.gap is not None else [],
        )
        for line in outline.lines
    ]
    doc = Document(format=fmt, front={key: value for key, value in front.items() if key != "format"}, sections=sections)
    return stamp(doc, store if store is not None else IdStore(Path(os.devnull) / "ids"))[0]
