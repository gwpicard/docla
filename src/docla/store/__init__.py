"""Immutable build versions and their page index."""

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

import docla
from docla.facts.layout import LayoutFacts
from docla.model import Document, Finding, Format
from docla.render.compose import Composition, component_for
from docla.render.marks import ElementMark, SectionMark
from docla.render.typst import TYPST_VERSION
from docla.theme import Theme


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ThemeRef(_Model):
    name: str
    version: str


class Gap(_Model):
    section: str | None
    text: str


class Chosen(_Model):
    section: str
    field: str
    chosen: str
    instead_of: str | None
    because: str


class FindingCounts(_Model):
    error: int
    warning: int
    info: int


class Residual(_Model):
    finding: str
    reason: str


class Cost(_Model):
    usd: float = 0.0
    by_role: dict[str, float] = Field(default_factory=dict)


class LookRecord(_Model):
    pages: int
    method: str = "marks"
    could_not: list[str] = Field(default_factory=list)
    clean: bool
    tiers: dict[str, str] = Field(default_factory=dict)


class Manifest(_Model):
    version: int
    written: str
    draft: bool
    final: bool
    doc_rev: int
    theme: ThemeRef | None
    typst: str
    engine: str
    doctype: str | None
    format: Format
    sections: int
    outputs: list[str]
    pdf_sha256: str
    gaps: list[Gap]
    chosen: list[Chosen]
    findings: FindingCounts
    residual: list[Residual] = Field(default_factory=list)
    look: LookRecord | None = None
    cost: Cost
    state: Literal["draft", "ready", "sent"] = "draft"
    sent_to: list[str] = Field(default_factory=list)
    forced_reason: str | None = None


class Version(_Model):
    number: int
    path: Path
    manifest: Manifest


class VersionImmutable(Exception):
    pass


def load_version(path: Path) -> Version:
    manifest = Manifest.model_validate_json((path / "manifest.json").read_text(encoding="utf-8"))
    return Version(number=manifest.version, path=path, manifest=manifest)


def _sections(facts: LayoutFacts, page: int) -> list[str]:
    ends = {m.id: m.page for m in facts.marks if isinstance(m, SectionMark) and m.edge == "end"}
    result: list[str] = []
    for mark in facts.marks:
        included = isinstance(mark, ElementMark) and mark.page == page
        if isinstance(mark, SectionMark) and mark.edge == "start":
            included = mark.page <= page <= ends.get(mark.id, mark.page)
        if included and mark.id not in result:
            result.append(mark.id)
    return result


def _regions(facts: LayoutFacts, page: int, sections: list[str]) -> list[dict[str, Any]]:
    elements = [m for m in facts.marks if isinstance(m, ElementMark) and m.page == page]
    regions: list[dict[str, Any]] = [
        {"section": m.id, "role": m.role, "x": m.x, "y": m.y, "w": m.w, "h": m.h} for m in elements
    ]
    for section in sections:
        if any(m.id == section for m in elements):
            continue
        boxes = [w.box for w in facts.words if w.section_id == section and w.box.page == page]
        if boxes:
            x, y = min(b.x0 for b in boxes), min(b.y0 for b in boxes)
            regions.append(
                {
                    "section": section,
                    "role": "section",
                    "x": x,
                    "y": y,
                    "w": max(b.x1 for b in boxes) - x,
                    "h": max(b.y1 for b in boxes) - y,
                }
            )
    return regions


def page_index(facts: LayoutFacts, findings: list[Finding]) -> list[dict[str, Any]]:
    result = []
    for page in facts.pages:
        sections = _sections(facts, page.page)
        result.append(
            {
                "page": page.page,
                "image": f"p{page.page:02d}.png",
                "width": page.width,
                "height": page.height,
                "sections": sections,
                "regions": _regions(facts, page.page, sections),
                "findings": [
                    f.id for f in findings if f.page == page.page or (f.page is None and f.section_id in sections)
                ],
            }
        )
    return result


def _manifest(
    number: int,
    doc_path: Path,
    doc: Document,
    pdf: Path,
    findings: list[Finding],
    theme: Theme | None,
    final: bool,
    look: LookRecord | None,
    residual: list[Residual] | None,
    cost: Cost | None,
    now: Callable[[], datetime] | None,
) -> Manifest:
    counts = Counter(f.severity for f in findings)
    gaps = [
        Gap(section=f.section_id, text=text)
        for f in findings
        if f.rule_id == "source.gap-present"
        for text in f.measured.get("gaps", [])
    ]
    chosen = [
        Chosen(
            section=s.id,
            field="component",
            chosen=s.component,
            instead_of=component_for(s.model_copy(update={"component": None}), doc.format, i, len(doc.sections)),
            because=s.because,
        )
        for i, s in enumerate(doc.sections)
        if s.id is not None and s.component and s.because
    ]
    return Manifest(
        version=number,
        written=(now() if now else datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        draft=not final,
        final=final,
        doc_rev=doc.rev,
        theme=ThemeRef(name=theme.info.name, version=theme.info.version) if theme else None,
        typst=TYPST_VERSION,
        engine=docla.__version__,
        doctype=doc.front.get("doctype"),
        format=doc.format,
        sections=len(doc.sections),
        outputs=[f"{doc_path.stem}.pdf"],
        pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
        gaps=gaps,
        chosen=chosen,
        findings=FindingCounts(error=counts["error"], warning=counts["warning"], info=counts["info"]),
        residual=residual or [],
        look=look,
        cost=cost or Cost(),
    )


def write_version(
    doc_path: Path,
    doc: Document,
    comp: Composition,
    pdf: Path,
    facts: LayoutFacts,
    findings: list[Finding],
    pngs: list[Path],
    heal: Path | None,
    *,
    theme: Theme | None = None,
    final: bool = False,
    look: LookRecord | None = None,
    residual: list[Residual] | None = None,
    cost: Cost | None = None,
    now: Callable[[], datetime] | None = None,
) -> Version:
    root = doc_path.parent / f"{doc_path.stem}.versions"
    root.mkdir(parents=True, exist_ok=True)
    numbers = [int(m.group(1)) for p in root.iterdir() if p.is_dir() and (m := re.fullmatch(r"v(\d+)", p.name))]
    number = max(numbers, default=0) + 1
    target = root / f"v{number}"
    temporary = Path(tempfile.mkdtemp(prefix=".version-", dir=root))
    try:
        manifest = _manifest(number, doc_path, doc, pdf, findings, theme, final, look, residual, cost, now)
        shutil.copyfile(pdf, temporary / f"{doc_path.stem}.pdf")
        (temporary / "composition.json").write_text(comp.model_dump_json(indent=2), encoding="utf-8")
        (temporary / "layout.json").write_text(facts.model_dump_json(indent=2), encoding="utf-8")
        (temporary / "findings.json").write_bytes(TypeAdapter(list[Finding]).dump_json(findings, indent=2))
        (temporary / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        pages = temporary / "pages"
        pages.mkdir()
        for i, png in enumerate(pngs, 1):
            shutil.copyfile(png, pages / f"p{i:02d}.png")
        (pages / "pages.json").write_text(
            json.dumps({"pages": page_index(facts, findings)}, indent=2), encoding="utf-8"
        )
        if heal is not None and heal.exists():
            shutil.copyfile(heal, temporary / "heal.jsonl")
            if (heal.parent / "heal").is_dir():
                shutil.copytree(heal.parent / "heal", temporary / "heal")
        if target.exists():
            raise VersionImmutable(f"Version already exists: {target}")
        os.rename(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return Version(number=number, path=target, manifest=manifest)


def update_manifest(path: Path, **changes: Any) -> Manifest:
    if changes.keys() - {"state", "sent_to", "forced_reason"}:
        raise VersionImmutable("Only delivery fields may change")
    manifest = Manifest.model_validate({**load_version(path).manifest.model_dump(), **changes})
    fd, name = tempfile.mkstemp(prefix=".manifest-", dir=path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(manifest.model_dump_json(indent=2))
        os.replace(name, path / "manifest.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return manifest
