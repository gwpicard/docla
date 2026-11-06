from itertools import groupby

from docla.checks.engine import CheckContext, make_finding, register
from docla.model import Finding, Provenance, Remedy, Rule, Scope
from docla.model.rules import Tier


@register("sequence")
class Sequence:
    tier: Tier = "source"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        for key, supported in (("over", "sections"), ("forbid_repeat", "component")):
            value = rule.check[key]
            if value != supported:
                raise ValueError(f"unsupported {key}: {value}")
        if ctx.composition is None:
            return []
        findings = []
        for component, group in groupby(ctx.composition.sections, key=lambda section: section.component):
            sections = [section.id for section in group]
            if len(sections) >= rule.check["window"]:
                findings.append(
                    make_finding(
                        rule,
                        ctx,
                        section_id=sections[0],
                        message=f"component {component} draws {len(sections)} consecutive sections",
                        measured={"component": component, "run": len(sections), "sections": sections},
                    )
                )
        return findings


RULES = [
    Rule(
        id="deck.no-component-three-running",
        title="No component draws three slides in a row",
        origin="manual",
        strength="soft",
        status="active",
        severity="warning",
        tier="source",
        scope=Scope(format="slides"),
        loop="macro",
        check={"kind": "sequence", "over": "sections", "window": 3, "forbid_repeat": "component"},
        remedy=Remedy.model_validate(
            {"class": "restructure", "hint": "switch a section to another component, or split or merge sections"}
        ),
        provenance=Provenance(source={"doc": "DESIGN.md", "section": "8.4 and 10.4"}),
    )
]
