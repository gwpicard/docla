from docla.checks import bounds, capacity, fit, gaps, palette, source, text
from docla.checks import dsl as dsl
from docla.model import Rule


def m1_rules() -> list[Rule]:
    """Return the built-in M1 rules, in the order their checks run."""
    return [*source.RULES, *fit.RULES, *bounds.RULES, *palette.RULES]


def all_rules() -> list[Rule]:
    """Return every built-in rule in catalogue order."""
    return [*m1_rules(), *source.M2_RULES, *text.RULES, *capacity.RULES, *gaps.RULES]
