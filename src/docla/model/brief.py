"""Intake brief models, storage and schema export."""

import argparse
import datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from docla.model.source import Format

FieldStatus = Literal["confirmed", "inferred", "defaulted", "skipped"]
BriefField = Literal[
    "doctype", "audience", "key_message", "ask", "scope", "topics", "metrics",
    "comparisons", "findings", "sensitivities", "exclusions", "tone", "length",
    "required_elements", "open_risks",
]
BRIEF_FIELDS: tuple[str, ...] = get_args(BriefField)
BRIEF_SUFFIX = ".brief.json"


class BriefModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldProvenance(BriefModel):
    status: FieldStatus
    evidence: list[str] = Field(default_factory=list)
    note: str | None = None
    person: str | None = None

    @model_validator(mode="after")
    def check_evidence(self) -> "FieldProvenance":
        if self.status == "inferred" and not self.evidence:
            raise ValueError("Inferred fields require evidence")
        return self


class Audience(BriefModel):
    who: str
    prior_knowledge: str | None = None
    decision: str | None = None


class Ask(BriefModel):
    kind: Literal["decide", "inform", "reassure"]
    text: str = ""


class BriefScope(BriefModel):
    period: str | None = None
    entities: list[str] = Field(default_factory=list)
    currency: str | None = None
    data_exclusions: list[str] = Field(default_factory=list)


class Topic(BriefModel):
    name: str
    data_ref: str | None = None
    include: bool = True
    order: int | None = None
    role: str | None = None


class Metric(BriefModel):
    name: str
    definition: str | None = None
    sources: list[str] = Field(default_factory=list)
    caveats: str | None = None


class Comparisons(BriefModel):
    primary: str | None = None
    secondary: list[str] = Field(default_factory=list)


class BriefFinding(BriefModel):
    claim: str
    evidence: list[str] = Field(default_factory=list)
    importance: Literal["lead", "support", "appendix"] = "support"
    explanation: str | None = None


class Sensitivity(BriefModel):
    item: str
    why: str | None = None
    presentation: str | None = None


class Tone(BriefModel):
    register: str | None = None
    person: Literal["first", "institutional"] | None = None
    detail: Literal["summary", "standard", "detailed"] | None = None


class Length(BriefModel):
    count: int | None = Field(default=None, ge=1)
    figures: Literal["figures", "tables", "mixed"] | None = None
    appendix: bool | None = None
    deadline: datetime.date | None = None
    delivery: Literal["pre-read", "presented"] | None = None


class RequiredElement(BriefModel):
    element: str
    source: str


class Brief(BriefModel):
    schema_version: Literal[1] = 1
    format: Format
    request: str = ""
    doctype: str | None = None
    audience: Audience | None = None
    key_message: str | None = None
    ask: Ask | None = None
    scope: BriefScope = Field(default_factory=BriefScope)
    topics: list[Topic] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    comparisons: Comparisons | None = None
    findings: list[BriefFinding] = Field(default_factory=list)
    sensitivities: list[Sensitivity] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    tone: Tone | None = None
    length: Length = Field(default_factory=Length)
    required_elements: list[RequiredElement] = Field(default_factory=list)
    open_risks: list[str] = Field(default_factory=list)
    provenance: dict[BriefField, FieldProvenance] = Field(default_factory=dict)

    def status(self, field: str) -> FieldStatus | None:
        if field not in BRIEF_FIELDS:
            raise ValueError(f"Unknown brief field: {field}")
        provenance = self.provenance.get(cast(BriefField, field))
        return provenance.status if provenance else None

    def length_unit(self) -> Literal["slides", "pages"]:
        return "slides" if self.format == "slides" else "pages"


class BriefError(Exception):
    """A stored brief is invalid."""


def brief_path(working_file: Path) -> Path:
    return working_file.with_name(working_file.stem + BRIEF_SUFFIX)


def load_brief(working_file: Path) -> Brief | None:
    path = brief_path(working_file)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        return Brief.model_validate_json(data)
    except ValidationError as error:
        raise BriefError(f"Invalid brief: {path}") from error


def save_brief(working_file: Path, brief: Brief) -> Path:
    path = brief_path(working_file)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            temp.write((brief.model_dump_json(indent=2) + "\n").encode("utf-8"))
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return path


def export_brief_schema(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "Brief.schema.json"
    path.write_text(
        json.dumps(Brief.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    export_brief_schema(parser.parse_args().directory)


if __name__ == "__main__":
    main()
