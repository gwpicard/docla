from docla.checks.engine import CheckContext, make_finding, register
from docla.model import Finding, Provenance, Remedy, Rule
from docla.model.rules import Tier


@register("image-resolves")
class ImageResolves:
    tier: Tier = "source"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        if ctx.assets is None:
            return []
        folders = ", ".join(str(folder) for folder in ctx.assets)
        return [
            make_finding(
                rule,
                ctx,
                message=f"image {section.image} was not found in: {folders}",
                section_id=section.id,
                measured={"image": section.image},
                severity="error" if ctx.final else "warning",
            )
            for section in ctx.doc.sections
            if section.image and not any((folder / section.image).is_file() for folder in ctx.assets)
        ]


RULES: list[Rule] = [
    Rule(
        id="source.image-resolves",
        title="Every section image resolves to a file",
        origin="manual",
        strength="hard",
        status="active",
        severity="warning",
        tier="source",
        check={"kind": "image-resolves"},
        remedy=Remedy.model_validate({"class": "ask", "hint": "supply the file in assets/ or name another image"}),
        provenance=Provenance(source={"doc": "PLAN-v0.1", "section": "B3.12"}),
    ),
]
