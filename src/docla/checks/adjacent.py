from docla.checks.engine import CheckContext, make_finding, register
from docla.model import Box, Finding, Provenance, Remedy, Rule
from docla.model.rules import Tier
from docla.render.marks import ElementMark


def _matches(mark: ElementMark, selector: dict) -> bool:
    roles = selector["role"]
    return mark.role in ([roles] if isinstance(roles, str) else roles)


def _figure(source: ElementMark, figures: list[ElementMark]) -> ElementMark | None:
    candidates = [mark for mark in figures if mark.id == source.id and mark.page == source.page]
    containing = [
        mark
        for mark in candidates
        if mark.x <= source.x
        and mark.y <= source.y
        and mark.x + mark.w >= source.x + source.w
        and mark.y + mark.h >= source.y + source.h
    ]
    if containing:
        return containing[0]
    above = [mark for mark in candidates if mark.y <= source.y]
    return max(above, key=lambda mark: mark.y + mark.h, default=None)


@register("adjacent")
class Adjacent:
    tier: Tier = "geometry"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        edge = rule.check["edge"]
        if edge != "bottom":
            raise ValueError(f"unsupported adjacent edge: {edge}")
        if ctx.facts is None:
            return []
        marks = [mark for mark in ctx.facts.marks if isinstance(mark, ElementMark)]
        figures = [mark for mark in marks if _matches(mark, rule.check["a"])]
        limit = float(rule.check["within_pt"])
        findings = []
        for source in (mark for mark in marks if _matches(mark, rule.check["b"])):
            figure = _figure(source, figures)
            if figure is None:
                continue
            gap = max(0.0, source.y - (figure.y + figure.h))
            if gap > limit:
                findings.append(
                    make_finding(
                        rule,
                        ctx,
                        section_id=source.id,
                        role=source.role,
                        page=source.page,
                        region=Box(x=source.x, y=source.y, w=source.w, h=source.h),
                        message=f"source gap is {gap:.1f} pt, above the limit of {limit:g} pt",
                        measured={"gap_pt": round(gap, 1), "within_pt": limit},
                    )
                )
        return findings


RULES = [
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
        remedy=Remedy.model_validate({"class": "tune", "hint": "move the source line directly below the figure"}),
        provenance=Provenance(source={"doc": "DESIGN.md", "section": "10.4 and 10.5"}),
    )
]
