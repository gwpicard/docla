"""Load and select the theme's visual critic rubric."""

from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from docla.model import Format, Remedy
from docla.model.rules import Severity
from docla.theme import Theme, ThemeError
from docla.theme.labels import load_provenance


class RubricApplies(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formats: list[Format] | None = None
    components: list[str] | None = None
    intents: list[str] | None = None


class RubricExamples(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    pass_: list[str] = Field(default_factory=list, alias="pass")
    fail: list[str] = Field(default_factory=list)


class RubricItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^sem\.[a-z0-9-]+$")
    question: str = Field(min_length=1)
    applies: RubricApplies = Field(default_factory=RubricApplies)
    severity: Severity
    remedy: Remedy
    view: Literal["page", "sheet"] = "page"
    examples: RubricExamples | None = None

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value

    @field_validator("remedy", mode="before")
    @classmethod
    def _remedy_keys(cls, value: Any) -> Any:
        if isinstance(value, dict) and set(value) - {"class", "hint"}:
            raise ValueError("unknown remedy key")
        return value


class Rubric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RubricItem]

    def ids(self) -> list[str]:
        return [item.id for item in self.items]

    def get(self, rubric_id: str) -> RubricItem:
        for item in self.items:
            if item.id == rubric_id:
                return item
        raise KeyError(rubric_id)

    def applies(
        self,
        format: Format,
        component: str | None = None,
        intent: str | None = None,
        *,
        view: Literal["page", "sheet"] = "page",
    ) -> list[RubricItem]:
        return [
            item
            for item in self.items
            if item.view == view
            and (item.applies.formats is None or format in item.applies.formats)
            and (item.applies.components is None or component in item.applies.components)
            and (item.applies.intents is None or intent in item.applies.intents)
        ]


def _check_examples(root: Path, rubric: Rubric) -> None:
    root = root.resolve()
    for item in rubric.items:
        if item.examples is None:
            continue
        for name in item.examples.pass_ + item.examples.fail:
            path = (root / name).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError(f"example is not a file under the theme root: {name}")


def load_rubric(theme: Theme) -> Rubric:
    path = theme.root / "rubric" / "visual.yaml"
    if not path.exists():
        return Rubric(items=[])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        rubric = Rubric.model_validate(data)
        if len(rubric.ids()) != len(set(rubric.ids())):
            raise ValueError("duplicate rubric id")
        _check_examples(theme.root, rubric)
        if theme.info.labelled:
            provenance = load_provenance(theme)
            for item in rubric.items:
                if item.id not in provenance.rubric:
                    raise ValueError(f"missing provenance for {item.id}")
        return rubric
    except (yaml.YAMLError, ValidationError, ValueError, OSError) as error:
        raise ThemeError(f"rubric/visual.yaml: {error}") from error


class CalibrationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    precision: float = Field(ge=0, le=1)
    recall: float | None = Field(default=None, ge=0, le=1)
    agreement: float | None = Field(default=None, ge=0, le=1)
    n: int | None = None


class _Calibration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: dict[str, CalibrationEntry]


def load_calibration(theme: Theme) -> dict[str, float]:
    path = theme.root / "rubric" / "calibration.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        calibration = _Calibration.model_validate(data)
        return {key: entry.precision for key, entry in calibration.items.items()}
    except (yaml.YAMLError, ValidationError, ValueError, OSError) as error:
        raise ThemeError(f"rubric/calibration.yaml: {error}") from error
