"""Apply a person's answer as a recorded brand change."""

import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

from docla.brand.changes import ChangeRecord, Evidence, begin_change, record_change
from docla.brand.departures import Departure, _format, set_token
from docla.brand.questions import QUESTIONS, BrandQuestion, DropRule, QuestionOption, SetToken, WriteRule, load_questions
from docla.brand.workspace import BrandError
from docla.theme import ThemeError, load_theme
from docla.theme.labels import ValueProvenance, ValueSource
from docla.theme.rules import load_theme_rules


class AnswerResult(BaseModel):
    question: BrandQuestion
    change: ChangeRecord
    departures: list[Departure]


def _select(question: BrandQuestion, option: str | None, text: str | None) -> QuestionOption | None:
    if question.answer is not None:
        raise BrandError(f"Question already answered: {question.id}")
    if not option and not text:
        raise BrandError("An option or text is required")
    selected = next ( (item for item in question.options if item.id == option), None )
    if (option and selected is None) or (question.options and selected is None):
        raise BrandError("A valid option is required")
    if selected:
        for effect in selected.effects:
            if isinstance(effect, SetToken):
                fmt = _format(effect.path)
                if question.format and fmt and fmt != question.format:
                    raise BrandError(f"Token format differs from question: {effect.path}")
    return selected


def _apply(brand: Path, question: BrandQuestion, selected: QuestionOption | None, text: str | None, person: str) -> list[Departure]:
    departures = []
    for effect in selected.effects if selected else []:
        if isinstance(effect, SetToken):
            note = selected.label if selected else text
            reason = selected.label if selected else (text or "")
            if selected and text:
                reason += f": {text}"
            departure = set_token(brand, effect.path, effect.value, provenance=ValueProvenance(
                label="answered", source=ValueSource(question=question.id, note=note)
            ), reason=reason, person=person, approved=True)
            if departure:
                departures.append(departure)
        elif isinstance(effect, WriteRule):
            rule = dict(effect.rule)
            rule["origin"] = "ingested"
            rule["provenance"] = {"label": "answered", "source": {"question": question.id, "note": selected.label}, "by": f"person:{person}"}
            path = brand / "theme/rules/ingested" / f"{rule['id']}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")
        elif isinstance(effect, DropRule):
            path = brand / "theme/rules/ingested" / f"{effect.id}.yaml"
            if not path.is_file():
                raise BrandError(f"Rule not found: {effect.id}")
            path.unlink()
    return departures


def answer_question(brand: Path, question_id: str, *, option: str | None = None, text: str | None = None, person: str = "owner") -> AnswerResult:
    questions = load_questions(brand)
    question = next((item for item in questions if item.id == question_id), None)
    if question is None:
        raise BrandError(f"Question not found: {question_id}")
    selected = _select(question, option, text)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dry_brand = Path(tmp)
            shutil.copytree(brand / "theme", dry_brand / "theme")
            _apply(dry_brand, question, selected, text, person)
            load_theme_rules(load_theme(dry_brand / "theme"))
    except ThemeError as error:
        raise BrandError(str(error)) from error

    name = re.sub(r"[^a-z0-9-]", "-", question.id)[:40]
    begin_change(brand, f"answer-{name}"[:41])
    departures = _apply(brand, question, selected, text, person)
    question.answer = text or (selected.label if selected else None)
    question.option = option
    question.answered_by = person
    question.answered_at = datetime.now(UTC).isoformat()
    (brand / QUESTIONS).write_text(yaml.safe_dump({"questions": [q.model_dump() for q in questions]}, sort_keys=False), encoding="utf-8")
    sources = ([question.source] if question.source else []) + question.evidence
    evidence = [Evidence(file=s.file, page=s.page, quote=s.quote) for s in sources]
    if not evidence:
        evidence = [Evidence(file=str(QUESTIONS), note=question.id)]
    change = record_change(brand, what=f"Answer {question.id}", why=question.text, evidence=evidence,
                           before=[], after=[], formats=[question.format] if question.format else ["slides", "doc"], person=person)
    return AnswerResult(question=question, change=change, departures=departures)
