"""Summarise finished sections using only their supported facts."""

import json
from collections.abc import Iterator

from docla.agents.client import Claude
from docla.agents.prompts import system_blocks
from docla.agents.writer import SectionDraft, SectionJob, draft_to_section
from docla.doctypes import Doctype, OutlineEntry
from docla.loop.guards import FactGuard
from docla.model import Document, Section
from docla.render.components import all_manifests
from docla.source.patches import PatchRejected
from docla.theme import Theme, neutral_theme


def _entries(entries: list[OutlineEntry]) -> Iterator[OutlineEntry]:
    for entry in entries:
        yield entry
        yield from _entries(entry.children)


def summary_sources(doc: Document, doctype: Doctype) -> dict[str, list[Section]]:
    entries = list(_entries(doctype.outline))
    summaries = {entry.section: entry for entry in entries if entry.fill == "summary"}
    result = {}
    for section in doc.sections:
        if section.id is None or section.section not in summaries:
            continue
        entry = summaries[section.section]
        if entry.from_:
            names = {child.section for root in entries if root.section in entry.from_ for child in _entries([root])}
            result[section.id] = [source for source in doc.sections if source.section in names]
        else:
            result[section.id] = [source for source in doc.sections if source.section not in summaries]
    return result


def _evidence(sections: list[Section]) -> list[str]:
    return [
        value
        for section in sections
        for value in (
            section.title or "",
            section.source_line or "",
            *section.paragraphs,
            *(part for item in section.items for part in (item.head or "", item.body, *item.sub)),
        )
    ]


async def summarise(
    claude: Claude, sections: list[Section], *, job: SectionJob, brief: str, theme: Theme | None = None
) -> SectionDraft:
    manifest = all_manifests()[job.component]
    texts = [section.model_dump(include={"id", "title", "items", "paragraphs"}, mode="json") for section in sections]
    prompt = (
        f'SECTION: outline line "{job.outline}", intent "{job.intent}", component "{manifest.label}".\n'
        f"CAPACITY: {manifest.capacity_text()}\n"
        "The summary may use only these texts:\n" + "\n".join(json.dumps(text, ensure_ascii=False) for text in texts)
    )
    content = [{"type": "text", "text": prompt}]
    keys = {citation.key for section in sections for item in section.items for citation in item.citations}
    guard = FactGuard(_evidence(sections), keys)
    doc = Document(front={}, format=job.format, sections=sections)
    system = system_blocks("summariser", theme or neutral_theme(), brief)
    for attempt in range(2):
        draft = await claude.call("summariser", SectionDraft, system=system, content=content, effort="medium")
        if guard(doc, draft_to_section(draft, job)):
            return draft
        unsupported = ", ".join(guard.unsupported)
        if attempt == 0:
            content = [
                *content,
                {"type": "text", "text": f"Unsupported: {unsupported}. Use only facts from the sections above."},
            ]
    raise PatchRejected("fact-support", unsupported)
