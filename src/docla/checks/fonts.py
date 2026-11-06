import re

from docla.checks.engine import CheckContext, make_finding, register
from docla.facts.layout import PlacedWord
from docla.model import Box, Finding, Provenance, Rule
from docla.model.rules import Tier


def family_of(pdf_font: str) -> str:
    """Extract the family from a PDF font name."""
    name = re.sub(r"^[A-Z]{6}\+", "", pdf_font)
    return name.rsplit("-", 1)[0]


def _key(name: str) -> str:
    return name.replace(" ", "").casefold()


def _allowed(ctx: CheckContext, rule: Rule) -> list[str] | None:
    if "allowed" in rule.check:
        return sorted(rule.check["allowed"])
    if ctx.theme is None:
        return None
    return sorted(family.name for family in ctx.theme.tokens.type.families.values())


def _finding(ctx: CheckContext, rule: Rule, word: PlacedWord, family: str, allowed: list[str]) -> Finding:
    box = word.box
    return make_finding(
        rule,
        ctx,
        section_id=word.section_id,
        page=box.page,
        region=Box(x=box.x0, y=box.y0, w=box.x1 - box.x0, h=box.y1 - box.y0),
        message=f"font {word.font} is not among the allowed families: {', '.join(allowed)}",
        measured={"font": family, "allowed": allowed},
    )


@register("font-family")
class FontFamily:
    tier: Tier = "geometry"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        allowed = _allowed(ctx, rule)
        if ctx.facts is None or allowed is None:
            return []
        keys = {_key(name) for name in allowed}
        seen: set[tuple[str | None, str]] = set()
        findings: list[Finding] = []
        for word in ctx.facts.words:
            family = family_of(word.font)
            identity = (word.section_id, family)
            if _key(family) not in keys and identity not in seen:
                seen.add(identity)
                findings.append(_finding(ctx, rule, word, family, allowed))
        return findings


RULES: list[Rule] = [
    Rule.model_validate(
        {
            "id": "geo.fonts",
            "title": "Text uses only the theme's type families",
            "origin": "manual",
            "strength": "hard",
            "status": "active",
            "severity": "error",
            "tier": "geometry",
            "check": {"kind": "font-family"},
            "remedy": {"class": "engine", "hint": "Use a font family named in the theme."},
            "provenance": Provenance(source={"doc": "DESIGN.md", "section": "10.5"}),
        }
    ),
]
