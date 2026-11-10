from docla.checks.engine import CheckContext, make_finding, register
from docla.doctypes import Doctype, Gap, conformance, load_doctypes
from docla.model import Finding, Provenance, Remedy, Rule
from docla.model.rules import Tier


def _section_id(ctx: CheckContext, doctype: Doctype, gap: Gap) -> str | None:
    if gap.kind == "missing":
        return None
    if gap.kind == "order":
        positions = {entry.section: index for index, entry in enumerate(doctype.outline)}
        highest = -1
        for section in ctx.doc.sections:
            if section.section not in positions:
                continue
            assert section.section is not None
            position = positions[section.section]
            if position < highest:
                return section.id
            highest = position
    return next((section.id for section in ctx.doc.sections if section.section == gap.section), None)


@register("outline-conforms")
class OutlineConforms:
    tier: Tier = "source"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        name = ctx.doc.front.get("doctype")
        doctype = load_doctypes().get(name) if isinstance(name, str) else None
        if doctype is None:
            return []
        return [
            make_finding(
                rule,
                ctx,
                message=gap.message,
                section_id=_section_id(ctx, doctype, gap),
                role=gap.section,
                measured={"kind": gap.kind, "section": gap.section},
                key=gap.kind,
            )
            for gap in conformance(ctx.doc, doctype)
        ]


RULES: list[Rule] = [
    Rule(
        id="source.outline-conforms",
        title="The document conforms to its outline",
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="source",
        check={"kind": "outline-conforms"},
        remedy=Remedy.model_validate({"class": "restructure", "hint": "restructure sections to match the outline"}),
        provenance=Provenance(source={"doc": "DESIGN.md", "section": "10.5"}),
    )
]
