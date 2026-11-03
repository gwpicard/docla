from docla.checks import bounds, fit, palette, source
from docla.model import Rule


def m1_rules() -> list[Rule]:
    """Return the built-in M1 rules, in the order their checks run."""
    return [*source.RULES, *fit.RULES, *bounds.RULES, *palette.RULES]
