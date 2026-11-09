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
from docla.checks.engine import _cell, fingerprint
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
    groups: dict[tuple[str, int], list[ElementMark]] = {}
    for mark in elements:
        groups.setdefault((mark.id, mark.page), []).append(mark)
    for (section, page), marks in groups.items():
        x, y = min(m.x for m in marks), min(m.y for m in marks)
        right, bottom = max(m.x + m.w for m in marks), max(m.y + m.h for m in marks)
        regions.append(Region(section, None, page, Box(x=x, y=y, w=right - x, h=bottom - y)))
    return regions


def critic_blocks() -> list[dict[str, Any]]:
    resources = files("docla.agents.prompts")
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": resources.joinpath(name).read_text(encoding="utf-8")}
        for name in ("header.txt", "critic.txt")
    ]
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _image_block(image: CriticImage) -> dict[str, Any]:
    data = image.png.read_bytes()
    with Image.open(io.BytesIO(data)) as png:
        if max(png.size) > 1568:
            png.thumbnail((1568, 1568), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            png.save(output, format="PNG")
            data = output.getvalue()
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(data).decode("ascii")},
    }


def _content(
    images: list[CriticImage], rubric: list[RubricItem], findings: list[Finding], regions: list[Region]
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for n, image in enumerate(images, 1):
        content.extend([{"type": "text", "text": f"Image {n} = {image.label}"}, _image_block(image)])
    lines = ["RUBRIC ITEMS (answer only these):"]
    lines.extend(f"- {item.id}: {item.question}" for item in rubric)
    lines.append("ALREADY REPORTED BY CODE (do not repeat):")
    lines.extend(f"- {f.rule_id} {f.section_id or '-'} {f.message}" for f in findings)
    if not findings:
        lines.append("none")
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


def _mapped_box(bbox: BBox | None, image: CriticImage | None) -> Box | None:
    if bbox is None or image is None:
        return None
    if not (0 <= bbox.x0 < bbox.x1 <= 1000 and 0 <= bbox.y0 < bbox.y1 <= 1000):
        return None
    return Box(
        x=bbox.x0 / 1000 * image.width,
        y=bbox.y0 / 1000 * image.height,
        w=(bbox.x1 - bbox.x0) / 1000 * image.width,
        h=(bbox.y1 - bbox.y0) / 1000 * image.height,
    )


def _anchor(box: Box | None, image: CriticImage | None, regions: list[Region]) -> Region | None:
    if box is None or image is None:
        return None
    x, y = box.x + box.w / 2, box.y + box.h / 2
    matches = [
        r
        for r in regions
        if r.page == image.page and r.box.x <= x <= r.box.x + r.box.w and r.box.y <= y <= r.box.y + r.box.h
    ]
    return min(matches, key=lambda r: r.box.w * r.box.h, default=None)


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


def _repeats(finding: Finding, engine: list[Finding], images: list[CriticImage]) -> bool:
    image = next((i for i in images if i.page == finding.page), None)
    if image is None or finding.region is None:
        return False
    size = (image.width, image.height)
    return any(
        f.page == finding.page
        and f.section_id == finding.section_id
        and f.role == finding.role
        and f.region is not None
        and _cell(f.region, size) == _cell(finding.region, size)
        for f in engine
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
    rubric = {item.id: item for item in rubric_items}
    findings: list[Finding] = []
    seen: set[str] = set()
    for item in report.items + report.anything_else:
        if item.verdict != "fail" or item.rubric_id not in rubric:
            continue
        finding = _finding(item, rubric[item.rubric_id], images, regions, format)
        if finding.fingerprint not in seen and not _repeats(finding, engine_findings, images):
            findings.append(finding)
            seen.add(finding.fingerprint)
    return findings


PRECISION_MIN = 0.8


def _overlaps(first: Box | None, second: Box | None) -> bool:
    return (
        first is not None
        and second is not None
        and min(first.x + first.w, second.x + second.w) > max(first.x, second.x)
        and min(first.y + first.h, second.y + second.h) > max(first.y, second.y)
    )


def _engine_agrees(finding: Finding, engine_findings: list[Finding]) -> bool:
    return finding.section_id is not None and any(
        engine.tier != "semantic"
        and engine.page == finding.page
        and engine.section_id == finding.section_id
        and _overlaps(engine.region, finding.region)
        for engine in engine_findings
    )


def _critic_agrees(finding: Finding, others: list[Finding]) -> bool:
    return any(
        other.rule_id == finding.rule_id and other.page == finding.page and _overlaps(other.region, finding.region)
        for other in others
    )


async def corroborate(
    claude: Claude,
    images: list[CriticImage],
    rubric_items: list[RubricItem],
    engine_findings: list[Finding],
    regions: list[Region],
    *,
    format: Format,
) -> list[Finding]:
    findings = await critique(claude, images, rubric_items, engine_findings, regions, format=format)
    agreed = [_engine_agrees(finding, engine_findings) for finding in findings]
    if all(agreed):
        return [finding.model_copy(update={"corroborated": True}) for finding in findings]
    second = await critique(claude, images, list(reversed(rubric_items)), engine_findings, regions, format=format)
    return [
        finding.model_copy(update={"corroborated": agrees or _critic_agrees(finding, second)})
        for finding, agrees in zip(findings, agreed, strict=True)
    ]


def calibrate(
    findings: list[Finding],
    calibration: dict[str, float],
    *,
    act_on_uncorroborated: bool = False,
    min_precision: float = PRECISION_MIN,
) -> list[Finding]:
    return [_calibrate_finding(f, calibration, act_on_uncorroborated, min_precision) for f in findings]


def _calibrate_finding(
    finding: Finding, calibration: dict[str, float], act_on_uncorroborated: bool, min_precision: float
) -> Finding:
    if finding.tier != "semantic":
        return finding.model_copy()
    updates: dict[str, Any] = {}
    if finding.rule_id not in calibration or calibration[finding.rule_id] < min_precision:
        updates["severity"] = "info"
    if finding.corroborated is not True and not act_on_uncorroborated:
        updates["remedy"] = finding.remedy.model_copy(update={"class_": "report"})
    return finding.model_copy(update=updates)
