from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from docla.checks.catalogue import all_rules
from docla.checks.engine import CHECKS
from docla.model import Rule
from docla.theme import Theme, ThemeError
from docla.theme.labels import check_rule_label


def _check_kind(check: dict[str, Any]) -> None:
    kind = check.get("kind")
    if not isinstance(kind, str) or kind not in CHECKS:
        raise ValueError(f"unknown check kind {kind!r}")
    if kind in ("all-of", "any-of", "not"):
        checks = check.get("checks")
        if not isinstance(checks, list):
            raise ValueError(f"{kind} requires a list of checks")
        for sub in checks:
            if not isinstance(sub, dict):
                raise ValueError(f"{kind} contains an invalid check")
            _check_kind(sub)


def _read_rule(path: Path, root: Path, origin: str, seen: set[str], *, labelled: bool) -> Rule:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        rule = Rule.model_validate(data)
        check_rule_label(rule, labelled=labelled)
        provenance = rule.provenance
        if not any((provenance.source, provenance.created, provenance.by)):
            raise ValueError("provenance must identify a source, date or author")
        _check_kind(rule.check)
        if rule.id in seen:
            raise ValueError(f"duplicate rule id {rule.id!r}")
        if rule.origin != origin:
            raise ValueError(f"origin must be {origin!r}")
    except (yaml.YAMLError, ValidationError, ValueError) as error:
        raise ThemeError(f"{path.relative_to(root)}: {error}") from error
    return rule


def load_theme_rules(theme: Theme) -> list[Rule]:
    """Load and validate the rules carried by a theme."""
    seen = {rule.id for rule in all_rules()}
    rules: list[Rule] = []
    for folder, origin in (("ingested", "ingested"), ("authored", "manual"), ("learned", "feedback")):
        for path in sorted((theme.root / "rules" / folder).glob("*.yaml")):
            rule = _read_rule(path, theme.root, origin, seen, labelled=theme.info.labelled)
            seen.add(rule.id)
            rules.append(rule)
    return rules
