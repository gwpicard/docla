from docla.checks.source import PROVENANCE
from docla.model import Remedy, Rule

RULES: list[Rule] = [
    Rule(
        id="source.title-label",
        title="A title is a label, not a question or a teaser",
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="source",
        check={"kind": "text-pattern", "field": "title", "regex": r"(\?|\.\.\.|…)\s*$", "must_not_match": True},
        remedy=Remedy.model_validate({"class": "redraft", "hint": "rewrite the title as a label that names the finding"}),
        provenance=PROVENANCE,
    ),
]
