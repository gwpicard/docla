"""Check that cited facts support the numbers written in items."""

import re
from collections.abc import Sequence
from decimal import Decimal

from docla.agents.gatherer import Fact
from docla.checks.engine import CheckContext, make_finding, register
from docla.loop.guards import NUM, NUMBER, fact_number_tokens
from docla.model import Citation, Finding, Provenance, Remedy, Rule
from docla.model.rules import Tier

YEAR = re.compile(r"(?:19|20)\d{2}")


def written_numbers(text: str) -> list[str]:
    return [token for match in NUM.finditer(text) if not YEAR.fullmatch(token := match.group().strip())]


def fact_numbers(fact: Fact) -> list[tuple[Decimal, bool]]:
    return [
        (abs(Decimal(token.replace(",", "").rstrip("%"))), token.endswith("%"))
        for token in fact_number_tokens(fact)
        if NUMBER.fullmatch(token)
    ]


def within_rounding(written: str, value: Decimal) -> bool:
    number = written.replace(",", "").rstrip("%")
    places = len(number.partition(".")[2])
    return abs(abs(Decimal(number)) - abs(value)) <= Decimal(5) * Decimal(10) ** (-places - 1)


def cited_facts(facts: Sequence[Fact], citation: Citation) -> list[Fact]:
    matching = [fact for fact in facts if fact.source_key == citation.key]
    located = [fact for fact in matching if citation.locator and fact.locator == citation.locator]
    return located or matching


@register("number-in-source")
class NumberInSource:
    tier: Tier = "source"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        if ctx.source_facts is None:
            return []
        findings = []
        for section in ctx.doc.sections:
            for i, item in enumerate(section.items):
                if not item.citations:
                    continue
                candidates = [fact for citation in item.citations for fact in cited_facts(ctx.source_facts, citation)]
                values = [pair for fact in candidates for pair in fact_numbers(fact)]
                citations = [f"{c.key} {c.locator}" if c.locator else c.key for c in item.citations]
                for text in (item.head or "", item.body, *item.sub):
                    for number in written_numbers(text):
                        if any(
                            percent == number.endswith("%") and within_rounding(number, value)
                            for value, percent in values
                        ):
                            continue
                        findings.append(
                            make_finding(
                                rule,
                                ctx,
                                section_id=section.id,
                                message=f"{number} is not in the cited source {citations}",
                                measured={"number": number, "item": i, "citations": citations},
                                key=f"{i}:{number}",
                            )
                        )
        return findings


RULES = [
    Rule(
        id="source.number-in-source",
        title="The cited source holds every quoted number",
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="source",
        check={"kind": "number-in-source"},
        remedy=Remedy.model_validate(
            {
                "class": "redraft",
                "hint": "use the number as the cited source states it, or cite the source that holds it",
            }
        ),
        provenance=Provenance(source={"doc": "PRODUCT.md", "section": "6"}),
    )
]
