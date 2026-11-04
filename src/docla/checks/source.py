from docla.checks.engine import CheckContext, make_finding, register
from docla.model import Finding, Provenance, Remedy, Rule, Section
from docla.model.rules import Tier
from docla.render.compose import component_for

PROVENANCE = Provenance(source={"doc": "DESIGN.md", "section": "10.5"})


@register("citations-resolve")
class CitationsResolve:
    tier: Tier = "source"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        listed = {source.key for source in ctx.doc.sources}
        return [
            make_finding(
                rule,
                ctx,
                message=f"citation key {citation.key} is not listed in ## Sources",
                section_id=section.id,
                measured={"key": citation.key},
            )
            for section in ctx.doc.sections
            for item in section.items
            for citation in item.citations
            if citation.key not in listed
        ]


def _is_empty(section: Section) -> bool:
    return not (section.title or section.items or section.paragraphs or section.data or section.image)


@register("empty-section")
class EmptySection:
    tier: Tier = "source"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        return [
            make_finding(rule, ctx, message="section has no title and no content", section_id=section.id)
            for section in ctx.doc.sections
            if _is_empty(section)
        ]


@register("intent-known")
class IntentKnown:
    tier: Tier = "source"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        fmt = ctx.doc.format
        return [
            make_finding(
                rule,
                ctx,
                message=f"intent {section.intent} has no component for format {fmt}",
                section_id=section.id,
                measured={"intent": section.intent, "format": fmt},
            )
            for section in ctx.doc.sections
            if component_for(section, fmt) is None
        ]


RULES: list[Rule] = [
    Rule(
        id="source.citations-resolve",
        title="Every citation key is listed in Sources",
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="source",
        check={"kind": "citations-resolve"},
        remedy=Remedy.model_validate({"class": "redraft", "hint": "cite a listed source or add it to ## Sources"}),
        provenance=PROVENANCE,
    ),
    Rule(
        id="source.empty-section",
        title="A section is not empty",
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="source",
        check={"kind": "empty-section"},
        remedy=Remedy.model_validate({"class": "redraft", "hint": "write the section's content or remove it"}),
        provenance=PROVENANCE,
    ),
]

M2_RULES: list[Rule] = [
    Rule(
        id="source.intent-known",
        title="Every section's intent has a component for the format",
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="source",
        check={"kind": "intent-known"},
        remedy=Remedy.model_validate(
            {"class": "restructure", "hint": "choose an intent or a component the format can draw"}
        ),
        provenance=PROVENANCE,
    ),
]
