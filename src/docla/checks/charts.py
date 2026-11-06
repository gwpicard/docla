from math import hypot
from typing import Any

from docla.checks.engine import CheckContext, make_finding, register
from docla.model import Box, Finding, Provenance, Remedy, Rule
from docla.model.rules import Tier
from docla.render.marks import ElementMark


def _box(mark: ElementMark) -> Box:
    return Box(x=mark.x, y=mark.y, w=mark.w, h=mark.h)


def _gaps(a: ElementMark, b: ElementMark) -> tuple[float, float]:
    return (
        max(0, a.x - b.x - b.w, b.x - a.x - a.w),
        max(0, a.y - b.y - b.h, b.y - a.y - a.h),
    )


def _labels(ctx: CheckContext, rule: Rule, labels: list[ElementMark], marks: list[ElementMark]) -> list[Finding]:
    findings = []
    tolerance = float(rule.check["tolerance_pt"])
    for index, (label, mark) in enumerate(zip(labels, marks, strict=False)):
        dx, dy = _gaps(label, mark)
        if dx > 2 * tolerance and dy > 2 * tolerance:
            findings.append(
                make_finding(
                    rule,
                    ctx,
                    section_id=label.id,
                    role=label.role,
                    page=label.page,
                    region=_box(label),
                    message=f"chart label {index} is away from its mark",
                    measured={"label": index, "off_pt": round(hypot(dx, dy), 1)},
                )
            )
    return findings


def _data(ctx: CheckContext, section_id: str) -> dict[str, Any] | None:
    if ctx.composition is None:
        return None
    section = next((s for s in ctx.composition.sections if s.id == section_id), None)
    if section is None:
        return None
    data = section.content.get("data")
    return data if isinstance(data, dict) and data.get("type") in ("bar", "column") else None


def _lengths(ctx: CheckContext, rule: Rule, marks: list[ElementMark], data: dict[str, Any]) -> list[Finding]:
    series = data.get("series", [])
    values = [
        max(0, s.get("values", [])[i] if i < len(s.get("values", [])) else 0)
        for i, _ in enumerate(data.get("categories", []))
        for s in series
    ]
    if not values or max(values) == 0 or not marks:
        return []
    lengths = [mark.w if data["type"] == "bar" else mark.h for mark in marks]
    scale = max(lengths) / max(values)
    tolerance = float(rule.check["length_tolerance_pt"])
    findings = []
    for index, (mark, value, length) in enumerate(zip(marks, values, lengths, strict=False)):
        expected = value * scale
        if abs(length - expected) > tolerance:
            findings.append(
                make_finding(
                    rule,
                    ctx,
                    section_id=mark.id,
                    role=mark.role,
                    page=mark.page,
                    region=_box(mark),
                    message=f"chart mark {index} length does not match its value",
                    measured={"mark": index, "value": value, "length_pt": length, "expected_pt": expected},
                )
            )
    return findings


@register("chart-labels")
class ChartLabels:
    tier: Tier = "geometry"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        if ctx.facts is None:
            return []
        groups: dict[str, dict[str, list[ElementMark]]] = {}
        for mark in ctx.facts.marks:
            if isinstance(mark, ElementMark) and mark.role in ("chart-label", "chart-mark"):
                groups.setdefault(mark.id, {"chart-label": [], "chart-mark": []})[mark.role].append(mark)
        findings: list[Finding] = []
        for section_id, group in groups.items():
            marks = group["chart-mark"]
            findings.extend(_labels(ctx, rule, group["chart-label"], marks))
            data = _data(ctx, section_id)
            if data is not None:
                findings.extend(_lengths(ctx, rule, marks, data))
        return findings


RULES = [
    Rule(
        id="geo.chart-labels",
        title="Chart labels sit by their marks and bars match their values",
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="geometry",
        check={"kind": "chart-labels", "tolerance_pt": 4, "length_tolerance_pt": 1},
        remedy=Remedy.model_validate({"class": "engine", "hint": "correct the chart layout and mark lengths"}),
        provenance=Provenance(source={"doc": "DESIGN.md", "section": "10.5"}),
    )
]
