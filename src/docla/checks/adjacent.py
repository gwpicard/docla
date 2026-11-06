from typing import Any

from docla.checks.engine import CheckContext, make_finding, register
from docla.model import Box, Finding, Provenance, Remedy, Rule
from docla.model.rules import Tier
from docla.render.marks import ElementMark


def _matches(mark: ElementMark, selector: dict[str, Any]) -> bool:
    roles = selector["role"]
    return mark.role in ([roles] if isinstance(roles, str) else roles)


def _contains(a: ElementMark, b: ElementMark) -> bool:
    return a.x <= b.x and a.y <= b.y and a.x + a.w >= b.x + b.w and a.y + a.h >= b.y + b.h


def _figure(marks: list[ElementMark], source: ElementMark) -> ElementMark | None:
    candidates = [m for m in marks if m.id == source.id and m.page == source.page]
    contained = [m for m in candidates if _contains(m, source)]
    if contained:
        return contained[0]
    above = [m for m in candidates if m.y <= source.y]
    return max(above, key=lambda m: m.y + m.h, default=None)


@register("adjacent")
class Adjacent:
    tier: Tier = "geometry"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        edge = rule.check["edge"]
        if edge != "bottom":
            raise ValueError(f"unsupported adjacent edge: {edge}")
        if ctx.facts is None:
            return []
        marks = [m for m in ctx.facts.marks if isinstance(m, ElementMark)]
        figures = [m for m in marks if _matches(m, rule.check["a"])]
        sources = [m for m in marks if _matches(m, rule.check["b"])]
        limit = rule.check["within_pt"]
        findings = []
        for source in sources:
            figure = _figure(figures, source)
            if figure is None:
                continue
            gap = max(0, source.y - (figure.y + figure.h))
            if gap > limit:
                findings.append(
                    make_finding(
                        rule,
                        ctx,
                        section_id=source.id,
                        role=source.role,
                        page=source.page,
                        region=Box(x=source.x, y=source.y, w=source.w, h=source.h),
                        message=f"gap is {gap:.1f} pt, exceeding the {limit} pt limit",
                        measured={"gap_pt": round(gap, 1), "within_pt": limit},
                    )
                )
        return findings


RULES: list[Rule] = [
    Rule(
        id="geo.figure-source",
        title="A source line sits directly under its figure",
        origin="manual",
        strength="soft",
        status="active",
        severity="warning",
        tier="geometry",
        check={
            "kind": "adjacent",
            "a": {"role": "figure"},
            "b": {"role": "figure-source"},
            "within_pt": 24,
            "edge": "bottom",
        },
        remedy=Remedy.model_validate({"class": "tune", "hint": "move the source line closer to the figure"}),
        provenance=Provenance(source={"doc": "DESIGN.md", "section": "10.4 and 10.5"}),
    ),
]
