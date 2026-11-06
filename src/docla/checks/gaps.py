import re
from collections.abc import Iterator
from typing import Any

from docla.checks.engine import CheckContext, make_finding, register
from docla.checks.source import PROVENANCE
from docla.model import Finding, Remedy, Rule, Section
from docla.model.rules import Tier
from docla.source.patches import TEXT_FIELDS

MARKER = re.compile(r"\[GAP:\s*([^\]]*)\]")


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _strings(nested)


def _section_gaps(section: Section) -> list[str]:
    fields = section.model_dump(include=set(TEXT_FIELDS))
    fields["items"] = [
        {key: item[key] for key in ("head", "body", "sub")} for item in fields["items"]
    ]
    texts = (
        text
        for field in TEXT_FIELDS
        for text in _strings(fields[field])
    )
    return [match.group(1) for text in texts for match in MARKER.finditer(text)]


@register("gap-present")
class GapPresent:
    tier: Tier = "source"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        return [
            make_finding(
                rule,
                ctx,
                message=f"{len(gaps)} gap marker(s), first: \"[GAP: {gaps[0]}]\"",
                section_id=section.id,
                measured={"gaps": gaps},
                severity="error" if ctx.final else "warning",
            )
            for section in ctx.doc.sections
            if (gaps := _section_gaps(section))
        ]


RULES: list[Rule] = [
    Rule(
        id="source.gap-present",
        title="Missing facts are reported",
        origin="manual",
        strength="hard",
        status="active",
        severity="warning",
        tier="source",
        check={"kind": "gap-present"},
        remedy=Remedy.model_validate({"class": "report", "hint": "provide the missing fact"}),
        provenance=PROVENANCE,
    ),
]
