"""Persistent questions raised during brand ingestion."""

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from docla.model.source import Format

QuestionKind = Literal["font", "gap", "identity", "conflict", "token", "confirm", "rule"]
QUESTIONS = Path("theme/ingest/questions.yaml")


class QuestionSource(BaseModel):
    file: str
    page: int | None = None
    quote: str | None = None
    crop: str | None = None


class SetToken(BaseModel):
    kind: Literal["set-token"]
    path: str
    value: Any


class WriteRule(BaseModel):
    kind: Literal["write-rule"]
    rule: dict[str, Any]


class DropRule(BaseModel):
    kind: Literal["drop-rule"]
    id: str


Effect = Annotated[SetToken | WriteRule | DropRule, Field(discriminator="kind")]


class QuestionOption(BaseModel):
    id: str
    label: str
    effects: list[Effect] = Field(default_factory=list)


class BrandQuestion(BaseModel):
    id: str
    kind: QuestionKind
    text: str
    source: QuestionSource | None = None
    format: Format | None = None
    blocking: bool = True
    answer: str | None = None
    answered_by: str | None = None
    answered_at: str | None = None
    evidence: list[QuestionSource] = Field(default_factory=list)
    options: list[QuestionOption] = Field(default_factory=list)
    recommended: str | None = None
    option: str | None = None


def load_questions(brand: Path) -> list[BrandQuestion]:
    path = brand / QUESTIONS
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [BrandQuestion.model_validate(item) for item in data.get("questions", [])]


def add_questions(brand: Path, questions: list[BrandQuestion]) -> list[BrandQuestion]:
    stored = load_questions(brand)
    by_id = {question.id: question for question in stored}
    added = []
    for question in questions:
        existing = by_id.get(question.id)
        if existing is None:
            stored.append(question)
            by_id[question.id] = question
            added.append(question)
        elif existing.answer is None:
            existing.text = question.text
            existing.source = question.source
            existing.blocking = question.blocking
            existing.evidence = question.evidence
            existing.options = question.options
            existing.recommended = question.recommended
    path = brand / QUESTIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"questions": [q.model_dump() for q in stored]}, sort_keys=False), encoding="utf-8")
    return added


def open_questions(brand: Path) -> list[BrandQuestion]:
    return [question for question in load_questions(brand) if question.answer is None]


def drop_open_questions(brand: Path, ids: list[str]) -> list[str]:
    stored = load_questions(brand)
    removed = [q.id for q in stored if q.id in ids and q.answer is None]
    if removed:
        path = brand / QUESTIONS
        kept = [q.model_dump() for q in stored if q.id not in removed or q.answer is not None]
        path.write_text(yaml.safe_dump({"questions": kept}, sort_keys=False), encoding="utf-8")
    return removed
