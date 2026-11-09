from pathlib import Path
from typing import cast

from PIL import Image

from docla.checks.engine import CheckContext, make_finding, register
from docla.model import Box, Finding, Provenance, Remedy, Rule
from docla.model.rules import Tier
from docla.render.marks import SectionMark


def _coverage(path: Path) -> float:
    with Image.open(path) as source:
        image = source.convert("RGB")
        colours = cast(list[tuple[int, tuple[int, int, int]]], image.getcolors(image.width * image.height))
        background = max(colours, key=lambda entry: entry[0])[1]
        ink = sum(
            count for count, colour in colours if any(abs(a - b) > 48 for a, b in zip(colour, background, strict=True))
        )
        return ink / (image.width * image.height)


@register("ink-coverage")
class InkCoverage:
    tier: Tier = "pixel"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        if ctx.facts is None:
            return []
        findings = []
        for page in ctx.facts.pages:
            sections = [
                mark.id
                for mark in ctx.facts.marks
                if isinstance(mark, SectionMark) and mark.edge == "start" and mark.page == page.page
            ]
            if ctx.composition is not None and any(
                section.id in sections and section.component in rule.check["skip_components"]
                for section in ctx.composition.sections
            ):
                continue
            coverage = _coverage(ctx.page_png(page.page))
            minimum = rule.check["min"]
            if coverage < minimum:
                findings.append(
                    make_finding(
                        rule,
                        ctx,
                        section_id=sections[0] if sections else None,
                        page=page.page,
                        region=Box(x=0, y=0, w=page.width, h=page.height),
                        measured={"coverage": round(coverage, 5), "min": minimum},
                        message=f"page {page.page} has ink coverage {coverage:.5f}",
                    )
                )
        return findings


RULES = [
    Rule(
        id="pix.blank-page",
        title="Pages are not blank",
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="pixel",
        check={"kind": "ink-coverage", "min": 0.001, "skip_components": ["chapter-break", "cover"]},
        remedy=Remedy.model_validate({"class": "restructure", "hint": "Add content or restructure the page."}),
        provenance=Provenance(source={"doc": "DESIGN.md", "section": "10.5"}),
    )
]
