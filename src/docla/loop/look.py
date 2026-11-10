"""Look over a rendered document with deterministic checks and a page critic."""

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from docla.agents.critic import Region, regions_from_facts
from docla.checks.catalogue import all_rules
from docla.checks.engine import CheckContext, run_checks
from docla.facts.layout import LayoutFacts, layout_facts
from docla.facts.raster import PdfiumRasteriser
from docla.model import Box, Document, Finding, Rule
from docla.render.compose import Composition, font_paths
from docla.render.kit import read_tokens
from docla.store import LookRecord, page_index
from docla.theme import Theme
from docla.theme.rules import load_theme_rules


@dataclass
class CriticPage:
    page: int
    png: Path
    width: float
    height: float
    sections: list[str]
    regions: list[Region]
    findings: list[Finding]
    components: dict[str, str] = field(default_factory=dict)
    intents: dict[str, str] = field(default_factory=dict)


PageCritic = Callable[[CriticPage], Awaitable[list[Finding]]]


@dataclass
class LookContext:
    doc: Document
    theme: Theme
    main: Path
    project: Path
    workdir: Path
    rules: list[Rule] | None = None
    critic: PageCritic | None = None
    final: bool = False
    assets: list[Path] | None = None
    clean_pages: frozenset[str] = frozenset()


class Look(BaseModel):
    pdf_sha256: str
    facts: LayoutFacts
    pngs: list[Path]
    findings: list[Finding]
    page_hashes: dict[int, str]
    critic_pages: list[int]
    clean_pages: frozenset[str]
    could_not: list[str]
    tiers: dict[str, str]

    def record(self) -> LookRecord:
        return LookRecord(
            pages=len(self.pngs),
            method="marks",
            could_not=self.could_not,
            tiers=self.tiers,
            clean=not self.could_not and not any(f.severity == "error" for f in self.findings),
        )


def _facts(pdf: Path, digest: str, ctx: LookContext) -> LayoutFacts:
    cache = ctx.project / ".docla" / "cache" / "facts" / f"{digest}.json"
    if cache.exists():
        return LayoutFacts.model_validate_json(cache.read_text(encoding="utf-8"))
    facts = layout_facts(pdf, ctx.main, ctx.main.parent, font_paths=font_paths(ctx.main.parent))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(facts.model_dump_json(), encoding="utf-8")
    return facts


def _regions(facts: LayoutFacts, page: int, sections: list[str], regions: list[Region]) -> list[Region]:
    result = [region for region in regions if region.page == page]
    for section in sections:
        if any(region.section_id == section for region in result):
            continue
        boxes = [word.box for word in facts.words if word.section_id == section and word.box.page == page]
        if boxes:
            x, y = min(box.x0 for box in boxes), min(box.y0 for box in boxes)
            result.append(
                Region(
                    section,
                    None,
                    page,
                    Box(
                        x=x,
                        y=y,
                        w=max(box.x1 for box in boxes) - x,
                        h=max(box.y1 for box in boxes) - y,
                    ),
                )
            )
    return result


async def look(pdf: Path, comp: Composition, ctx: LookContext) -> Look:
    pngs = PdfiumRasteriser().render(pdf, ctx.workdir / "pages")
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    facts = _facts(pdf, digest, ctx)
    check_ctx = CheckContext(
        ctx.doc,
        facts,
        read_tokens(ctx.main.parent),
        theme=ctx.theme,
        composition=comp,
        final=ctx.final,
        assets=ctx.assets,
        pages_png=pngs,
    )
    rules = ctx.rules if ctx.rules is not None else all_rules() + load_theme_rules(ctx.theme)
    tiers = {tier: "ok" for tier in ("source", "geometry", "pixel")}
    findings = [
        finding for tier in tiers for finding in run_checks([rule for rule in rules if rule.tier == tier], check_ctx)
    ]
    hashes = {number: hashlib.sha256(png.read_bytes()).hexdigest() for number, png in enumerate(pngs, 1)}
    clean = set(ctx.clean_pages)
    called: list[int] = []
    could_not: list[str] = []
    regions = regions_from_facts(facts)
    for page in page_index(facts, findings):
        number = page["page"]
        page_findings = [finding for finding in findings if finding.id in page["findings"]]
        if (
            ctx.critic is None
            or hashes[number] in ctx.clean_pages
            or any(finding.severity == "error" for finding in page_findings)
        ):
            continue
        critic_page = CriticPage(
            number,
            pngs[number - 1],
            page["width"],
            page["height"],
            page["sections"],
            _regions(facts, number, page["sections"], regions),
            page_findings,
            {s.id: s.component for s in comp.sections if s.id in page["sections"]},
            {s.id: s.intent for s in ctx.doc.sections if s.id in page["sections"] and s.id is not None},
        )
        called.append(number)
        try:
            result = await ctx.critic(critic_page)
        except Exception as exc:
            could_not.append(f"semantic page {number}: {exc}")
            continue
        findings.extend(result)
        if not any(finding.severity in ("error", "warning") for finding in result):
            clean.add(hashes[number])
    tiers["semantic"] = "failed" if could_not else "ok" if called else "skipped"
    return Look(
        pdf_sha256=digest,
        facts=facts,
        pngs=pngs,
        findings=findings,
        page_hashes=hashes,
        critic_pages=called,
        clean_pages=frozenset(clean),
        could_not=could_not,
        tiers=tiers,
    )
