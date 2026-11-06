from docla.checks.engine import CheckContext, make_finding, register
from docla.facts.layout import PlacedImage
from docla.model import Box, Finding, Provenance, Rule
from docla.model.rules import Tier


def _finding(ctx: CheckContext, rule: Rule, image: PlacedImage, minimum: float) -> Finding:
    dpi = min(image.dpi_x, image.dpi_y)
    box = image.box
    return make_finding(
        rule,
        ctx,
        section_id=image.section_id,
        role=image.role,
        page=box.page,
        region=Box(x=box.x0, y=box.y0, w=box.x1 - box.x0, h=box.y1 - box.y0),
        message=f"image effective resolution {dpi:.1f} DPI is below the minimum {minimum:g} DPI",
        measured={"dpi": round(dpi, 1), "min": minimum},
    )


@register("image-dpi")
class ImageDpi:
    tier: Tier = "geometry"

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        if not ctx.final or ctx.facts is None:
            return []
        imagery = ctx.theme.tokens.imagery if ctx.theme is not None else None
        minimum = imagery.min_dpi if imagery is not None else rule.check["min"]
        return [
            _finding(ctx, rule, image, minimum) for image in ctx.facts.images if min(image.dpi_x, image.dpi_y) < minimum
        ]


RULES: list[Rule] = [
    Rule.model_validate(
        {
            "id": "geo.image-dpi",
            "title": "Images have at least the theme's minimum resolution",
            "origin": "manual",
            "strength": "hard",
            "status": "active",
            "severity": "error",
            "tier": "geometry",
            "check": {"kind": "image-dpi", "min": 150},
            "remedy": {"class": "restructure", "hint": "Choose another component or a larger image."},
            "provenance": Provenance(source={"doc": "DESIGN.md", "section": "10.5"}),
        }
    ),
]
