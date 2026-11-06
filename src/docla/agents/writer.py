"""Draft a single section from cited facts."""

from pydantic import BaseModel, Field

from docla.agents.client import Claude
from docla.agents.gatherer import Fact
from docla.agents.prompts import system_blocks
from docla.model import Citation, Format, Item, Section
from docla.render.components import all_manifests
from docla.theme import Theme, neutral_theme


class SectionJob(BaseModel):
    section_id: str
    format: Format
    intent: str
    component: str
    outline: str
    section: str | None = None
    audience: str = ""
    purpose: str = ""


class DraftItem(BaseModel):
    head: str | None = None
    body: str
    priority: int = Field(ge=1)
    citations: list[Citation] = Field(default_factory=list)


class SectionDraft(BaseModel):
    title: str | None = None
    items: list[DraftItem] = Field(default_factory=list)
    paragraphs: list[str] = Field(default_factory=list)


def _fact_line(fact: Fact) -> str:
    key = fact.source_key if fact.locator is None else f"{fact.source_key} {fact.locator}"
    return f'<source key="{key}">{fact.text}</source>'


async def draft(
    claude: Claude,
    job: SectionJob,
    facts: list[Fact],
    brief: str,
    exemplar: str | None = None,
    *,
    theme: Theme | None = None,
) -> SectionDraft:
    try:
        manifest = all_manifests()[job.component]
    except KeyError as error:
        raise ValueError(f"Unknown component: {job.component}") from error

    fact_lines = "\n".join(_fact_line(fact) for fact in facts)
    exemplar_line = "EXEMPLAR: none" if exemplar is None else f"EXEMPLAR (a well-formed section): {exemplar}"
    prompt = (
        f"Write one section of a {job.format} document for {job.audience}. Purpose: {job.purpose}.\n"
        f'SECTION: outline line "{job.outline}", intent "{job.intent}", component "{manifest.label}".\n'
        f"CAPACITY: {manifest.capacity_text()}\n"
        f"FACTS (the only material you may use; each has a key):\n{fact_lines}\n"
        f"{exemplar_line}\n"
        "TASK: Write the section as the schema requires. Use only the facts. Cite every number with its key. "
        "Rank items by importance in priority (1 = most important). If a needed fact is missing, "
        "write [GAP: ...]. Titles are labels, not questions or teasers."
    )
    return await claude.call(
        "writer.draft",
        SectionDraft,
        system=system_blocks("writer.draft", theme if theme is not None else neutral_theme(), brief),
        content=[{"type": "text", "text": prompt}],
        effort="medium",
    )


def draft_to_section(draft: SectionDraft, job: SectionJob) -> Section:
    return Section(
        id=job.section_id,
        intent=job.intent,
        section=job.section,
        title=draft.title,
        items=[Item(head=item.head, body=item.body, citations=item.citations) for item in draft.items],
        paragraphs=draft.paragraphs,
    )
