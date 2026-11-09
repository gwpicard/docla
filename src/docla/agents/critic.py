"""Judge rendered images against a closed visual rubric."""

import base64
import hashlib
import io
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, Field

from docla.agents.client import Claude
from docla.checks.engine import GRID, fingerprint
from docla.facts.layout import LayoutFacts
from docla.model import Box, Finding, Format
from docla.render.marks import ElementMark
from docla.theme.rubric import RubricItem


class BBox(BaseModel):
    x0: int
    y0: int
    x1: int
    y1: int


class CriticItem(BaseModel):
    rubric_id: str
    verdict: Literal["pass", "fail", "unsure"]
    image: int
    bbox: BBox | None
    evidence: str


class CriticReport(BaseModel):
    items: list[CriticItem]
    anything_else: list[CriticItem] = Field(default_factory=list)


@dataclass
class CriticImage:
    png: Path
    page: int
    width: float
    height: float
    label: str


@dataclass
class Region:
    section_id: str
    role: str | None
    page: int
    box: Box


def regions_from_facts(facts: LayoutFacts) -> list[Region]:
    elements = [m for m in facts.marks if isinstance(m, ElementMark)]
    regions = [Region(m.id, m.role, m.page, Box(x=m.x, y=m.y, w=m.w, h=m.h)) for m in elements]
    groups: dict[tuple[str, int], list[Box]] = {}
    for region in regions:
        groups.setdefault((region.section_id, region.page), []).append(region.box)
    for (section, page), boxes in groups.items():
        x, y = min(b.x for b in boxes), min(b.y for b in boxes)
        right, bottom = max(b.x + b.w for b in boxes), max(b.y + b.h for b in boxes)
        regions.append(Region(section, None, page, Box(x=x, y=y, w=right - x, h=bottom - y)))
    return regions


def critic_blocks() -> list[dict[str, Any]]:
    resources = files("docla.agents.prompts")
    blocks = [
        {"type": "text", "text": resources.joinpath(name).read_text(encoding="utf-8")}
        for name in ("header.txt", "critic.txt")
    ]
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _image_block(image: CriticImage) -> dict[str, Any]:
    data = image.png.read_bytes()
    with Image.open(io.BytesIO(data)) as source:
        if max(source.size) > 1568:
            source.thumbnail((1568, 1568), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            source.save(output, format="PNG")
            data = output.getvalue()
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(data).decode("ascii")},
    }


def _content(
    images: list[CriticImage], rubrics: list[RubricItem], findings: list[Finding], regions: list[Region]
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for n, image in enumerate(images, 1):
        content.extend([{"type": "text", "text": f"Image {n} = {image.label}"}, _image_block(image)])
    lines = ["RUBRIC ITEMS (answer only these):"]
    lines.extend(f"- {r.id}: {r.question}" for r in rubrics)
    lines.append("ALREADY REPORTED BY CODE (do not repeat):")
    lines.extend([f"- {f.rule_id} {f.section_id or '-'} {f.message}" for f in findings] or ["none"])
    lines.append("REGIONS (normalised 0..1000, use these to anchor):")
    for n, image in enumerate(images, 1):
        for region in regions:
            if region.page == image.page:
                b = region.box
                coords = (
                    round(b.x / image.width * 1000),
                    round(b.y / image.height * 1000),
                    round((b.x + b.w) / image.width * 1000),
                    round((b.y + b.h) / image.height * 1000),
                )
                lines.append(f"- image {n} {region.section_id} {region.role or 'section'} {' '.join(map(str, coords))}")
    content.append({"type": "text", "text": "\n".join(lines)})
    return content


def _mapped_box(b: BBox | None, image: CriticImage | None) -> Box | None:
    if b is None or image is None or not (0 <= b.x0 < b.x1 <= 1000 and 0 <= b.y0 < b.y1 <= 1000):
        return None
    return Box(
        x=b.x0 * image.width / 1000,
        y=b.y0 * image.height / 1000,
        w=(b.x1 - b.x0) * image.width / 1000,
        h=(b.y1 - b.y0) * image.height / 1000,
    )


def _anchor(box: Box | None, image: CriticImage | None, regions: list[Region]) -> Region | None:
    if box is None or image is None:
        return None
    x, y = box.x + box.w / 2, box.y + box.h / 2
    candidates = [
        r
        for r in regions
        if r.page == image.page and r.box.x <= x <= r.box.x + r.box.w and r.box.y <= y <= r.box.y + r.box.h
    ]
    return min(candidates, key=lambda r: r.box.w * r.box.h, default=None)


def _cell(box: Box, image: CriticImage) -> tuple[int, int]:
    return (
        min(max(int((box.x + box.w / 2) / image.width * GRID), 0), GRID - 1),
        min(max(int((box.y + box.h / 2) / image.height * GRID), 0), GRID - 1),
    )


def _repeat(finding: Finding, image: CriticImage | None, existing: list[Finding]) -> bool:
    if image is None or finding.region is None:
        return False
    return any(
        f.page == finding.page
        and f.section_id == finding.section_id
        and f.role == finding.role
        and f.region is not None
        and _cell(f.region, image) == _cell(finding.region, image)
        for f in existing
    )


def _finding(
    item: CriticItem, rubric: RubricItem, images: list[CriticImage], regions: list[Region], format: Format
) -> Finding:
    image = images[item.image - 1] if 1 <= item.image <= len(images) else None
    box = _mapped_box(item.bbox, image)
    anchor = _anchor(box, image, regions)
    section = anchor.section_id if anchor else None
    role = anchor.role if anchor else None
    size = (image.width, image.height) if image else None
    fp = fingerprint(item.rubric_id, section, role, box, size)
    measured: dict[str, Any] = {"image": item.image}
    if item.bbox is not None:
        measured["bbox"] = [item.bbox.x0, item.bbox.y0, item.bbox.x1, item.bbox.y1]
    return Finding(
        id=hashlib.sha1(f"{item.rubric_id}|{section}|{fp}".encode()).hexdigest()[:12],
        rule_id=item.rubric_id,
        tier="semantic",
        severity=rubric.severity if anchor else "info",
        format=format,
        section_id=section,
        role=role,
        page=image.page if image else None,
        region=box,
        message=item.evidence,
        measured=measured,
        fingerprint=fp,
        remedy=rubric.remedy,
        corroborated=False,
    )


async def critique(
    claude: Claude,
    images: list[CriticImage],
    rubric_items: list[RubricItem],
    engine_findings: list[Finding],
    regions: list[Region],
    *,
    format: Format,
) -> list[Finding]:
    if not images or not rubric_items:
        return []
    report = await claude.call(
        "critic",
        CriticReport,
        system=critic_blocks(),
        content=_content(images, rubric_items, engine_findings, regions),
        effort="medium",
    )
    rubrics = {r.id: r for r in rubric_items}
    findings: list[Finding] = []
    seen: set[str] = set()
    for item in report.items + report.anything_else:
        if item.verdict != "fail" or item.rubric_id not in rubrics:
            continue
        finding = _finding(item, rubrics[item.rubric_id], images, regions, format)
        image = images[item.image - 1] if 1 <= item.image <= len(images) else None
        if finding.fingerprint not in seen and not _repeat(finding, image, engine_findings):
            findings.append(finding)
            seen.add(finding.fingerprint)
    return findings
