from collections import defaultdict

from docla.checks.engine import CheckContext, make_finding, register
from docla.facts.layout import LayoutFacts, PlacedShape, PlacedWord
from docla.facts.models import FactBox, PageFacts
from docla.model import Box, Finding, Provenance, Rule
from docla.model.rules import Tier

PROVENANCE = Provenance(source={"doc": "DESIGN.md", "section": "10.5"})

Placed = PlacedWord | PlacedShape


def _sectioned(facts: LayoutFacts) -> list[Placed]:
    items: list[Placed] = [*facts.words, *facts.shapes]
    return [item for item in items if item.section_id is not None]


def _region(boxes: list[FactBox]) -> Box:
    x0 = min(b.x0 for b in boxes)
    y0 = min(b.y0 for b in boxes)
    return Box(x=x0, y=y0, w=max(b.x1 for b in boxes) - x0, h=max(b.y1 for b in boxes) - y0)


def _outside_by(box: FactBox, page: PageFacts, margin: float) -> float:
    """Return how far the box lies beyond the page inset by `margin`, or 0 when it lies within."""
    return max(
        0.0,
        margin - box.x0,
        margin - box.y0,
        box.x1 - (page.width - margin),
        box.y1 - (page.height - margin),
    )


Hit = tuple[Placed, float]


def _safe_area_finding(rule: Rule, ctx: CheckContext, key: tuple[str, int], hits: list[Hit]) -> Finding:
    section_id, page = key
    worst = round(max(d for _, d in hits), 1)
    return make_finding(
        rule,
        ctx,
        message=f"{len(hits)} items lie outside the safe area, by up to {worst} pt",
        section_id=section_id,
        page=page,
        region=_region([item.box for item, _ in hits]),
        measured={"count": len(hits), "max_outside_pt": worst},
    )


@register("in-safe-area")
class InSafeArea:
    tier: Tier = "geometry"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        facts = ctx.facts
        if facts is None:
            return []
        margin = float(rule.check["margin_pt"][ctx.doc.format])
        tolerance = float(rule.check["tolerance_pt"])
        pages = {page.page: page for page in facts.pages}
        outside: dict[tuple[str, int], list[Hit]] = defaultdict(list)
        for item in _sectioned(facts):
            by = _outside_by(item.box, pages[item.box.page], margin)
            if by > tolerance:
                outside[(str(item.section_id), item.box.page)].append((item, by))
        return [_safe_area_finding(rule, ctx, key, hits) for key, hits in outside.items()]


def _font_finding(rule: Rule, ctx: CheckContext, smallest: PlacedWord, minimum: float) -> Finding:
    return make_finding(
        rule,
        ctx,
        message=f"text at {smallest.size:.1f} pt is below the minimum of {minimum:g} pt",
        section_id=smallest.section_id,
        page=smallest.box.page,
        region=_region([smallest.box]),
        measured={"size": smallest.size, "min": minimum},
    )


@register("font-size")
class MinFont:
    tier: Tier = "geometry"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        facts = ctx.facts
        if facts is None:
            return []
        minimum = rule.check["min_pt"][ctx.doc.format]
        smallest: dict[str, PlacedWord] = {}
        for word in facts.words:
            if word.section_id is not None:
                smallest[word.section_id] = min(smallest.get(word.section_id, word), word, key=lambda w: w.size)
        return [_font_finding(rule, ctx, word, minimum) for word in smallest.values() if word.size < minimum]


RULES: list[Rule] = [
    Rule.model_validate(
        {
            "id": "geo.in-safe-area",
            "title": "Content stays inside the page margins",
            "origin": "manual",
            "strength": "hard",
            "status": "active",
            "severity": "error",
            "tier": "geometry",
            "check": {"kind": "in-safe-area", "margin_pt": {"slides": 40, "doc": 56.69}, "tolerance_pt": 1},
            "remedy": {"class": "restructure", "hint": "split or shorten the content so it stays inside the margins"},
            "provenance": PROVENANCE,
        }
    ),
    Rule.model_validate(
        {
            "id": "geo.min-font",
            "title": "Text is at least the format's minimum size",
            "origin": "manual",
            "strength": "hard",
            "status": "active",
            "severity": "error",
            "tier": "geometry",
            "check": {"kind": "font-size", "min_pt": {"slides": 18, "doc": 9}},
            "remedy": {"class": "redraft", "hint": "cut the text so it fits at the minimum size or larger"},
            "provenance": PROVENANCE,
        }
    ),
]
