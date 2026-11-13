"""Persistent questions raised during brand ingestion."""

from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

from docla.model.source import Format

QuestionKind = Literal["font"]
QUESTIONS = Path("theme/ingest/questions.yaml")


class QuestionSource(BaseModel):
    file: str
    page: int | None = None
    quote: str | None = None


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
    path = brand / QUESTIONS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"questions": [q.model_dump() for q in stored]}, sort_keys=False), encoding="utf-8")
    return added


def open_questions(brand: Path) -> list[BrandQuestion]:
    return [question for question in load_questions(brand) if question.answer is None]
