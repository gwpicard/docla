from collections import Counter
from pathlib import Path
from typing import cast

from PIL import Image

from docla.checks.engine import CheckContext, make_finding, register
from docla.facts.layout import PlacedWord
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


def _luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


def contrast_ratio(a: str, b: str) -> float:
    lighter, darker = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _background(image: Image.Image, word: PlacedWord, scale: float) -> str | None:
    box = word.box
    outer = (
        max(0, int((box.x0 - 4) * scale)),
        max(0, int((box.y0 - 4) * scale)),
        min(image.width, int((box.x1 + 4) * scale)),
        min(image.height, int((box.y1 + 4) * scale)),
    )
    inner = (
        max(outer[0], int((box.x0 - 1) * scale)),
        max(outer[1], int((box.y0 - 1) * scale)),
        min(outer[2], int((box.x1 + 1) * scale)),
        min(outer[3], int((box.y1 + 1) * scale)),
    )
    x0, y0, x1, y1 = outer
    a, b, c, d = inner
    counts: Counter[tuple[int, int, int]] = Counter()
    for region in ((x0, y0, x1, b), (x0, d, x1, y1), (x0, b, a, d), (c, b, x1, d)):
        if region[0] < region[2] and region[1] < region[3]:
            crop = image.crop(region)
            colours = cast(list[tuple[int, tuple[int, int, int]]], crop.getcolors(crop.width * crop.height))
            counts.update({colour: count for count, colour in colours})
    if not counts:
        return None
    return "#{:02X}{:02X}{:02X}".format(*counts.most_common(1)[0][0])


@register("contrast")
class Contrast:
    tier: Tier = "pixel"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        if ctx.facts is None:
            return []
        minimum = ctx.theme.tokens.colour.contrast_min if ctx.theme is not None else rule.check["min"]
        lowest: dict[tuple[str | None, str | None], tuple[float, Finding]] = {}
        for page in ctx.facts.pages:
            with Image.open(ctx.page_png(page.page)) as source:
                image = source.convert("RGB")
                for word in ctx.facts.words:
                    if word.box.page != page.page or word.colour is None:
                        continue
                    background = _background(image, word, image.width / page.width)
                    if background is None:
                        continue
                    ratio = contrast_ratio(word.colour, background)
                    key = (word.section_id, word.role)
                    if ratio >= minimum or (key in lowest and lowest[key][0] <= ratio):
                        continue
                    box = word.box
                    finding = make_finding(
                        rule,
                        ctx,
                        section_id=word.section_id,
                        role=word.role,
                        page=box.page,
                        region=Box(x=box.x0, y=box.y0, w=box.x1 - box.x0, h=box.y1 - box.y0),
                        measured={
                            "ratio": round(ratio, 2),
                            "min": minimum,
                            "text": word.colour,
                            "background": background,
                        },
                        message=f"{word.text!r} contrast {ratio:.2f} between {word.colour} and {background}",
                    )
                    lowest[key] = (ratio, finding)
        return [finding for _, finding in lowest.values()]


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
    ),
    Rule(
        id="pix.contrast",
        title="Text contrasts with its background",
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="pixel",
        check={"kind": "contrast", "min": 4.5},
        remedy=Remedy.model_validate(
            {"class": "engine", "hint": "Use text and background colours with sufficient contrast."}
        ),
        provenance=Provenance(source={"doc": "DESIGN.md", "section": "10.5"}),
    ),
]
