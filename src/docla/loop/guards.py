"""Fact support and preservation checks for section rewrites."""

import re
from collections.abc import Collection, Sequence
from decimal import Decimal, InvalidOperation, localcontext

from docla.agents.gatherer import Fact
from docla.checks.engine import CheckContext, make_finding
from docla.model import Document, Finding, Provenance, Remedy, Rule, Section

NUM = re.compile(r"(?<![\w.])[-+]?\d[\d,.]*\d%?|\b\d%?")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = re.compile(rf"\b(?:19|20)\d{{2}}\b|\b\d{{1,2}}\s+(?:{MONTHS})\b", re.IGNORECASE)
ENT = re.compile(r"\b[A-Z][a-zA-Z&-]+(?:[ ]+[A-Z][a-zA-Z&-]+)+\b")
WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty"
).split()
WORD_NUMBERS = {word: str(i) for i, word in enumerate(WORDS)}
WORD = re.compile(r"\b(?:" + "|".join(WORDS) + r")\b", re.IGNORECASE)
CALC = re.compile(r"^\s*calc:\s*(sum|difference|ratio|percentage)\(([^()]*)\)\s*=\s*([-+]?\d[\d,]*(?:\.\d+)?%?)\s*$")
NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")


def support_tokens(text: str) -> set[str]:
    text = WORD.sub(lambda match: WORD_NUMBERS[match.group().lower()], text)
    return (
        {match.group().replace(",", "") for match in NUM.finditer(text)}
        | {match.group().lower() for match in DATE.finditer(text)}
        | {match.group().lower() for match in ENT.finditer(text)}
    )


def _fields(section: Section) -> list[str]:
    return [
        section.title or "",
        section.source_line or "",
        *section.paragraphs,
        *(value for item in section.items for value in (item.head or "", item.body, *item.sub)),
    ]


def fact_tokens(section: Section) -> set[str]:
    return set().union(*(support_tokens(value) for value in _fields(section)))


def fact_number_tokens(fact: Fact) -> set[str]:
    tokens = {token for token in support_tokens(fact.text) if NUMBER.fullmatch(token)}
    if fact.value is not None:
        value = format(fact.value, "f")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        tokens.add(value)
        if fact.kind == "percent":
            tokens.add(value + "%")
    return tokens


def resolve_numbers(section: Section, facts: Sequence[Fact]) -> dict[str, list[str]]:
    return {
        token: sorted(fact.id for fact in facts if fact.id is not None and token in fact_number_tokens(fact))
        for token in fact_tokens(section)
        if NUMBER.fullmatch(token)
    }


def _calculation(line: str, allowed: set[str]) -> tuple[str, list[str]] | None:
    match = CALC.fullmatch(line)
    if not match:
        return None
    op, raw_operands, raw_result = match.groups()
    operands = [operand.strip().replace(",", "") for operand in raw_operands.split(",")]
    result = raw_result.replace(",", "")
    if (
        not operands
        or any(not NUMBER.fullmatch(x) or x not in allowed for x in operands)
        or (op != "sum" and len(operands) != 2)
        or (op == "percentage") != result.endswith("%")
    ):
        return None
    try:
        values = [Decimal(x.rstrip("%")) for x in operands]
        expected = Decimal(result.rstrip("%"))
        with localcontext() as ctx:
            ctx.prec = 50
            if op == "sum":
                value = sum(values, Decimal(0))
            elif op == "difference":
                value = values[0] - values[1]
            else:
                value = values[0] / values[1]
                if op == "percentage":
                    value *= 100
            places = len(result.rstrip("%").partition(".")[2])
            if value.quantize(Decimal(1).scaleb(-places)) == expected:
                return result, operands
    except (InvalidOperation, ZeroDivisionError):
        pass
    return None


class FactGuard:
    def __init__(
        self,
        evidence: Sequence[str],
        citation_keys: Collection[str] | None = None,
        *,
        facts: Sequence[Fact] = (),
        numbers_from_facts: bool = False,
    ):
        self.allowed = set().union(*(support_tokens(text) for text in evidence))
        for fact in facts:
            self.allowed.update(support_tokens(fact.text), fact_number_tokens(fact))
        self.facts = facts
        self.numbers_from_facts = numbers_from_facts
        self.citation_keys = citation_keys
        self.unsupported: list[str] = []
        self.resolved: dict[str, list[str]] = {}

    def __call__(self, doc: Document, section: Section) -> bool:
        calculations = [
            calculation
            for line in (section.note or "").splitlines()
            if (calculation := _calculation(line, self.allowed)) is not None
        ]
        derived = {result for result, _ in calculations}
        self.resolved = resolve_numbers(section, self.facts)
        for result, operands in calculations:
            if result in self.resolved and not self.resolved[result]:
                self.resolved[result] = sorted(
                    {
                        fact.id
                        for fact in self.facts
                        if fact.id is not None and any(operand in fact_number_tokens(fact) for operand in operands)
                    }
                )
        unsupported = fact_tokens(section) - self.allowed - derived
        if self.numbers_from_facts:
            unsupported.update(token for token, ids in self.resolved.items() if not ids)
        if self.citation_keys is not None:
            unsupported.update(
                f"cite:{citation.key}"
                for item in section.items
                for citation in item.citations
                if citation.key not in self.citation_keys
            )
        self.unsupported = sorted(unsupported)
        return not self.unsupported


def kept_facts(before: Section, after: Section) -> list[str]:
    return sorted(fact_tokens(before) & fact_tokens(after))


def _rule(rule_id: str, title: str, hint: str) -> Rule:
    return Rule(
        id=rule_id,
        title=title,
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="source",
        check={"kind": "fact-guard"},
        remedy=Remedy.model_validate({"class": "redraft", "hint": hint}),
        provenance=Provenance(source={"doc": "DESIGN.md", "section": "11.5", "spike": "docs/spikes/S4-repair.md"}),
    )


RULES = [
    _rule("source.fact-support", "Facts are supported", "Remove the token or write [GAP: ...]."),
    _rule("source.facts-kept", "Facts are kept", "Keep the fact; a fact a title cannot hold may move into an item."),
]


def check_rewrite(before: Document, after: Document) -> list[Finding]:
    sections = {section.id: section for section in before.sections if section.id is not None}
    common_evidence = [f"{source.key} {source.text}" for source in before.sources]
    common_evidence.extend(value for value in before.front.values() if isinstance(value, str))
    findings: list[Finding] = []
    for section in after.sections:
        if section.id is None or section.id not in sections:
            continue
        original = sections[section.id]
        keys = {source.key for source in before.sources}
        keys.update(citation.key for item in original.items for citation in item.citations)
        guard = FactGuard([*_fields(original), *common_evidence], keys)
        guard(after, section)
        lost = sorted(fact_tokens(original) - fact_tokens(section))
        for rule, tokens in zip(RULES, (guard.unsupported, lost), strict=True):
            if tokens:
                findings.append(
                    make_finding(
                        rule,
                        CheckContext(after),
                        section_id=section.id,
                        message=f"{rule.title}: {', '.join(tokens)}",
                        measured={"tokens": tokens},
                    )
                )
    return findings
