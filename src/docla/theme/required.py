"""Required brand elements and their provenance."""

from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from docla.model.source import Format
from docla.theme.labels import ValueProvenance
from docla.theme.loader import ThemeError
from docla.theme.models import Theme

RequiredKind = Literal["author", "date", "disclaimer", "logo", "page-number", "confidentiality", "contact", "other"]
REQUIRED_FILE = "required.yaml"


class RequiredElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    element: RequiredKind
    name: str
    text: str | None = None
    place: str | None = None
    formats: list[Format] = Field(default_factory=list)
    provenance: ValueProvenance

    @field_validator("provenance", mode="before")
    @classmethod
    def _rule_provenance(cls, value: object) -> object:
        # Rule provenance may also carry the author of the synthesis.
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k != "by"}
        return value


class RequiredElements(BaseModel):
    model_config = ConfigDict(extra="forbid")
    elements: list[RequiredElement]


def load_required(theme: Theme) -> list[RequiredElement]:
    path = theme.root / REQUIRED_FILE
    if not path.exists():
        return []
    try:
        elements = RequiredElements.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).elements
        if len({item.id for item in elements}) != len(elements):
            raise ValueError("duplicate element id")
        return elements
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as error:
        raise ThemeError(f"{REQUIRED_FILE}: {error}") from error
