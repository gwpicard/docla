"""Draft and repair a single section."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from docla.agents.client import Claude, image_block
from docla.agents.gatherer import Fact
from docla.agents.prompts import system_blocks
from docla.model import Citation, Finding, Format, Item, Patch, PatchOp, Section
from docla.render.components import all_manifests
from docla.source.patches import PatchRejected
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


class RepairOp(BaseModel):
    op: Literal["set_fields", "replace_section", "insert_after", "delete_section", "set_attr", "move_section"]
    section_id: str
    title: str | None = None
    items: list[Item] | None = None
    paragraphs: list[str] | None = None


class RepairReply(BaseModel):
    reason: str
    ops: list[RepairOp]


def _finding_lines(finding: Finding, number: int) -> list[str]:
    role = f"{finding.role} " if finding.role is not None else ""
    lines = [f"  {number}. [{finding.rule_id}] {role}{finding.message} Hint: {finding.remedy.hint}"]
    measured = dict(finding.measured)
    items = measured.get("items")
    if isinstance(items, list):
        del measured["items"]
        lines.append("     Height only drops in whole lines. Lines per item, measured:")
        for item in items:
            line = f"       items[{item['n']}]: {item['lines']} line(s)"
            if item["cut_to_save_line"] is not None:
                line += (
                    f"; cutting about {item['cut_to_save_line']} characters brings it to {item['lines'] - 1} line(s)"
                )
            lines.append(line)
    if measured:
        lines.append(f"     measured: {json.dumps(measured, sort_keys=True)}")
    return lines


def _repair_prompt(section: Section, findings: list[Finding], history: list[str]) -> str:
    current = json.dumps(
        section.model_dump(include={"id", "title", "items", "paragraphs"}), sort_keys=True, ensure_ascii=False
    )
    lines = [f"CURRENT SECTION (JSON): {current}", "FINDINGS (from code that measured the rendered result):"]
    for number, finding in enumerate(findings, 1):
        lines.extend(_finding_lines(finding, number))
    lines.extend(["EARLIER ATTEMPTS:", *history] if history else ["EARLIER ATTEMPTS: none"])
    lines.extend(
        [
            "Do not repeat a change that did not work.",
            "Change only what the findings require. Keep every fact, number, citation and the item order "
            "unless a finding requires otherwise. Do not add facts. Prefer shortening wording to deleting an item.",
            "A fact a title cannot hold may move into an item; do not drop it.",
            "Return a set_fields patch only.",
        ]
    )
    return "\n".join(lines)


def _repair_ops(reply: RepairReply, section_id: str | None) -> list[PatchOp]:
    if not reply.ops:
        raise PatchRejected("repair-empty", f"No operations for section {section_id}")
    ops = []
    for op in reply.ops:
        if op.op != "set_fields":
            raise PatchRejected("repair-op", f"Invalid repair operation {op.op}")
        if op.section_id != section_id:
            raise PatchRejected("repair-op", f"Invalid repair section {op.section_id}")
        fields = op.model_dump(include={"title", "items", "paragraphs"}, exclude_none=True)
        if op.items is not None:
            fields["items"] = [item.model_dump() for item in op.items]
        if not fields:
            raise PatchRejected("repair-empty", f"No fields for section {section_id}")
        ops.append(PatchOp(op="set_fields", section_id=op.section_id, fields=fields))
    return ops


async def repair(
    claude: Claude,
    section: Section,
    findings: list[Finding],
    history: list[str],
    brief: str,
    images: list[Path] | None = None,
    *,
    base_rev: int = 0,
    theme: Theme | None = None,
) -> Patch:
    content: list[dict[str, Any]] = []
    for number, path in enumerate(images or [], 1):
        description = (
            "the section as rendered, with each finding's region outlined in red"
            if number == 1
            else "the same section, clean"
        )
        content.extend([{"type": "text", "text": f"Image {number}: {description}"}, image_block(path)])
    content.append({"type": "text", "text": _repair_prompt(section, findings, history)})
    reply = await claude.call(
        "writer.repair",
        RepairReply,
        system=system_blocks("writer.repair", theme if theme is not None else neutral_theme(), brief),
        content=content,
        effort="medium",
    )
    return Patch(
        base_rev=base_rev,
        author="ai",
        reason=reply.reason,
        finding_ids=[finding.id for finding in findings],
        ops=_repair_ops(reply, section.id),
    )


def _fact_line(fact: Fact) -> str:
    key = fact.source_key if fact.locator is None else f"{fact.source_key} {fact.locator}"
    prefix = f"{fact.id} " if fact.id is not None else ""
    return prefix + f'<source key="{key}">{fact.text}</source>'


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
