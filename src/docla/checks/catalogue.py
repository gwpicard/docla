from docla.checks import (
    adjacent,
    assets,
    bounds,
    capacity,
    figures,
    fit,
    fonts,
    gaps,
    images,
    outline,
    palette,
    source,
    text,
)
from docla.checks import dsl as dsl
from docla.model import Provenance, Remedy, Rule
from docla.source import parser


def parser_rules() -> list[Rule]:
    """Describe findings produced directly by the source parser."""
    records = [
        ("appearance-in-source", "Appearance belongs in the theme", "engine", "Move appearance to the theme."),
        ("unknown-attribute", "Section attributes are known", "report", "Remove or correct the unknown attribute."),
        ("parse-error", "The working file can be parsed", "report", "Correct the syntax of the working file."),
        ("missing-intent", "Every section has an intent", "report", "Add an intent to the section."),
        ("invalid-format", "The document format is valid", "report", "Set the format to slides or doc."),
    ]
    return [_parser_rule(*record) for record in records]


def _parser_rule(name: str, title: str, remedy_class: str, hint: str) -> Rule:
    severity = parser.SEVERITY[name]
    return Rule(
        id=f"source.{name}",
        title=title,
        origin="manual",
        status="active",
        tier="source",
        severity=severity,  # type: ignore[arg-type]
        strength="hard" if severity == "error" else "soft",
        check={"kind": "parser"},
        remedy=Remedy.model_validate({"class": remedy_class, "hint": hint}),
        provenance=Provenance(source={"doc": "DESIGN.md", "section": "5.2"}),
    )


def m1_rules() -> list[Rule]:
    """Return the built-in M1 rules, in the order their checks run."""
    return [*source.RULES, *fit.RULES, *bounds.RULES, *palette.RULES]


def all_rules() -> list[Rule]:
    """Return every built-in rule in catalogue order."""
    return [
        *m1_rules(),
        *source.M2_RULES,
        *text.RULES,
        *capacity.RULES,
        *gaps.RULES,
        *figures.RULES,
        *assets.RULES,
        *fonts.RULES,
        *images.RULES,
        *adjacent.RULES,
    ]


def document_rules() -> list[Rule]:
    """Return opt-in document rules."""
    return [*outline.RULES]
