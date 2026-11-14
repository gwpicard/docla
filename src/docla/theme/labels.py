"""Value labels and their sources in a theme."""

from typing import Any, Literal, Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from docla.model import Rule
from docla.model.rules import ValueLabel
from docla.theme.loader import ThemeError
from docla.theme.models import Theme

LABEL_NAMES = {"measured": "Measured", "derived": "Derived", "inferred": "Inferred", "answered": "Answered"}
SourceRole = Literal["guidelines", "templates", "examples", "logos", "fonts", "notes"]
PROVENANCE_FILE = "provenance.yaml"


class ValueSource(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    file: str | None = None
    files: list[str] = Field(default_factory=list)
    role: SourceRole | None = None
    page: int | None = None
    quote: str | None = None
    question: str | None = None
    from_: list[str] = Field(default_factory=list, alias="from")
    note: str | None = None


class ValueProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: ValueLabel
    source: ValueSource

    @model_validator(mode="after")
    def _source_matches_label(self) -> Self:
        source = self.source
        if self.label == "measured" and (not (source.file or source.files) or not source.role):
            raise ValueError("measured values require a file and role")
        if self.label == "derived" and not source.from_:
            raise ValueError("derived values require from")
        if self.label == "inferred" and not (source.note and source.note.strip()):
            raise ValueError("inferred values require a note")
        if self.label == "answered" and not (source.question and source.question.strip()):
            raise ValueError("answered values require a question")
        return self


class ThemeProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tokens: dict[str, ValueProvenance] = Field(default_factory=dict)
    rubric: dict[str, ValueProvenance] = Field(default_factory=dict)


def token_paths(data: dict[str, Any]) -> list[str]:
    def leaves(mapping: dict[str, Any], prefix: str = "") -> list[str]:
        paths = []
        for key, value in mapping.items():
            if not prefix and key == "schema":
                continue
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                paths.extend(leaves(value, path))
            else:
                paths.append(path)
        return paths

    return sorted(leaves(data))


def _raw_paths(theme: Theme) -> list[str]:
    data = yaml.safe_load((theme.root / "tokens.yaml").read_text(encoding="utf-8"))
    return token_paths(data)


def load_provenance(theme: Theme) -> ThemeProvenance:
    path = theme.root / PROVENANCE_FILE
    if not path.is_file() and not theme.info.labelled:
        return ThemeProvenance()
    try:
        return ThemeProvenance.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as error:
        raise ThemeError(f"{PROVENANCE_FILE}: {error}") from error


def _covering_label(entries: dict[str, ValueProvenance], path: str) -> ValueProvenance:
    parts = path.split(".")
    while parts:
        key = ".".join(parts)
        if key in entries:
            return entries[key]
        parts.pop()
    raise KeyError(path)


def token_label(theme: Theme, path: str) -> ValueProvenance:
    if path not in _raw_paths(theme):
        raise KeyError(path)
    return _covering_label(load_provenance(theme).tokens, path)


def check_token_labels(theme: Theme) -> None:
    entries = load_provenance(theme).tokens
    paths = _raw_paths(theme)
    for key in entries:
        if len(key.split(".")) < 2 or not any(path == key or path.startswith(key + ".") for path in paths):
            raise ThemeError(f"{PROVENANCE_FILE}: unknown token path {key}")
    for path in paths:
        try:
            _covering_label(entries, path)
        except KeyError as error:
            raise ThemeError(f"{PROVENANCE_FILE}: missing label for {path}") from error


def check_rule_label(rule: Rule, *, labelled: bool) -> None:
    label = rule.provenance.label
    if label is None:
        if labelled:
            raise ValueError("rule requires a provenance label")
        return
    provenance = ValueProvenance(label=label, source=ValueSource.model_validate(rule.provenance.source or {}))
    source = provenance.source
    if label == "measured" and source.role == "examples" and (rule.strength != "soft" or rule.status != "proposed"):
        raise ValueError("rules measured from examples must be soft and proposed")
    if label == "measured" and rule.strength == "hard":
        if source.role != "templates" and not (source.role == "guidelines" and source.quote and source.quote.strip()):
            raise ValueError("hard measured rules require a template or quoted guidelines")
