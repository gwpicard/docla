import math
from collections.abc import Iterator

from docla.checks.engine import CheckContext, make_finding, register
from docla.facts.layout import LayoutFacts
from docla.facts.models import FactBox
from docla.model import Box, Finding, Provenance, Rule
from docla.model.rules import Tier

PROVENANCE = Provenance(source={"doc": "DESIGN.md", "section": "10.5"})

# D65 reference white for CIE XYZ to CIELAB.
WHITE = (0.95047, 1.0, 1.08883)

Lab = tuple[float, float, float]


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _f(t: float) -> float:
    return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29


def lab(colour: str) -> Lab:
    """Return the CIELAB (D65) coordinates of an sRGB `#RRGGBB` colour."""
    r, g, b = (_linear(int(colour[i : i + 2], 16) / 255) for i in (1, 3, 5))
    x = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = 0.0193 * r + 0.1192 * g + 0.9505 * b
    fx, fy, fz = (_f(v / w) for v, w in zip((x, y, z), WHITE, strict=True))
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(a: str, b: str) -> float:
    """Return the CIE76 colour difference between two `#RRGGBB` colours."""
    return math.dist(lab(a), lab(b))


def nearest(colour: str, tokens: dict[str, str]) -> tuple[str, float]:
    return min(((name, delta_e(colour, value)) for name, value in tokens.items()), key=lambda pair: pair[1])


def _region(box: FactBox) -> Box:
    return Box(x=box.x0, y=box.y0, w=box.x1 - box.x0, h=box.y1 - box.y0)


def _coloured(facts: LayoutFacts) -> Iterator[tuple[str, str, FactBox]]:
    """Yield the section id, colour and box of every word colour and shape fill or stroke inside a section."""
    for word in facts.words:
        if word.section_id is not None and word.colour is not None:
            yield word.section_id, word.colour, word.box
    for shape in facts.shapes:
        if shape.section_id is not None:
            for colour in (shape.fill, shape.stroke):
                if colour is not None:
                    yield shape.section_id, colour, shape.box


def _finding(rule: Rule, ctx: CheckContext, section_id: str, colour: str, box: FactBox) -> Finding:
    name, distance = nearest(colour, ctx.tokens)
    return make_finding(
        rule,
        ctx,
        message=f"colour {colour} is off the palette; the nearest token is {name} (delta E {distance:.1f})",
        section_id=section_id,
        page=box.page,
        region=_region(box),
        measured={"colour": colour, "nearest": name, "delta_e": round(distance, 1)},
    )


@register("colour-in-set")
class ColourInSet:
    tier: Tier = "geometry"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        if ctx.facts is None or not ctx.tokens:
            return []
        tolerance = float(rule.check.get("tolerance", 2.0))
        first: dict[tuple[str, str], FactBox] = {}
        for section_id, colour, box in _coloured(ctx.facts):
            if (section_id, colour) not in first and nearest(colour, ctx.tokens)[1] > tolerance:
                first[(section_id, colour)] = box
        return [_finding(rule, ctx, section_id, colour, box) for (section_id, colour), box in first.items()]


RULES: list[Rule] = [
    Rule.model_validate(
        {
            "id": "geo.palette",
            "title": "Every colour inside a section is a theme colour",
            "origin": "manual",
            "strength": "hard",
            "status": "active",
            "severity": "error",
            "tier": "geometry",
            "check": {"kind": "colour-in-set", "tolerance": 2.0},
            "remedy": {"class": "engine", "hint": "use a theme colour token through colour(name)"},
            "provenance": PROVENANCE,
        }
    ),
]
