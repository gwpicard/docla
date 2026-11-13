# Intent: People answer evidenced brand questions and their decisions become recorded brand changes.
import importlib
import importlib.util
import shutil
from pathlib import Path

import pytest
import yaml

import docla
from docla.brand.git import run_git
from docla.brand.workspace import BrandError, init_brand
from docla.theme import load_theme
from docla.theme.rules import load_theme_rules


def _module(name):
    if importlib.util.find_spec(name) is None:
        return None
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not str(error.name).startswith(name + "."):
            raise
        if importlib.util.find_spec(error.name) is not None:
            raise
        return None


questions = _module("docla.brand.questions")
answers = _module("docla.brand.answers")
labels = _module("docla.theme.labels")
changes = _module("docla.brand.changes")


def _interfaces():
    for module, members in (
        (questions, ("BrandQuestion", "add_questions", "load_questions")),
        (answers, ("AnswerResult", "answer_question")),
        (labels, ("token_label",)),
        (changes, ("change_log",)),
    ):
        assert module is not None, "the public question and answer modules must exist"
        for member in members:
            assert hasattr(module, member), f"{module.__name__}.{member} must exist"


def _rule(kind="text-pattern"):
    return {
        "id": "brand.titles-short",
        "title": "Keep titles short",
        "origin": "ingested",
        "strength": "soft",
        "status": "active",
        "severity": "warning",
        "tier": "source",
        "check": {"kind": kind, "field": "title", "regex": ".{1,60}", "must_match": True},
        "remedy": {"class": "redraft", "hint": "Shorten the title"},
        "provenance": {"by": "owner"},
    }


def _brand(tmp_path):
    _interfaces()
    brand = init_brand("acme", tmp_path / ".brand")
    theme = brand / "theme"
    shutil.rmtree(theme)
    shutil.copytree(Path(docla.__file__).resolve().parent / "themes/neutral", theme)
    provenance = {
        "tokens": {
            "colour": {"label": "inferred"},
            "type": {"label": "inferred"},
            "pages.doc": {
                "label": "measured",
                "source": {"file": "materials/guidelines/book.pdf", "page": 33, "quote": "Margins are 20 mm"},
            },
            "pages.slides": {"label": "answered", "source": {"question": "q-1"}},
            "spacing": {"label": "inferred"},
            "imagery": {"label": "inferred"},
        }
    }
    (theme / "provenance.yaml").write_text(yaml.safe_dump(provenance, sort_keys=False))
    source = {
        "file": "materials/guidelines/book.pdf",
        "page": 33,
        "quote": "Margins are 20 mm",
        "crop": "crops/book-33.png",
    }
    data = [
        {
            "id": "conflict.pages.doc.margin.top",
            "kind": "conflict",
            "text": "Which margin?",
            "format": "doc",
            "blocking": True,
            "source": source,
            "evidence": [source, {"file": "materials/examples/report.pdf", "page": 2, "crop": "crops/report-2.png"}],
            "options": [
                {
                    "id": "a",
                    "label": "20 mm (guidelines)",
                    "effects": [{"kind": "set-token", "path": "pages.doc.margin.top", "value": "20mm"}],
                },
                {
                    "id": "b",
                    "label": "18 mm (examples)",
                    "effects": [{"kind": "set-token", "path": "pages.doc.margin.top", "value": "18mm"}],
                },
            ],
            "recommended": "a",
        },
        {
            "id": "confirm.rule.titles-short",
            "kind": "confirm",
            "text": "Keep titles short?",
            "format": "slides",
            "blocking": False,
            "options": [
                {"id": "yes", "label": "Yes", "effects": [{"kind": "write-rule", "rule": _rule()}]},
                {"id": "no", "label": "No"},
            ],
        },
        {"id": "gap.no-logo", "kind": "gap", "text": "Is there a logo?", "blocking": False},
    ]
    questions.add_questions(brand, [questions.BrandQuestion.model_validate(item) for item in data])
    run_git(brand, "add", "-A")
    run_git(brand, "commit", "-m", "Prepare questions")
    return brand


def _files(path):
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def _state(brand):
    return (
        run_git(brand, "rev-list", "--count", "main"),
        run_git(brand, "branch", "--show-current"),
        _files(brand / "theme"),
        run_git(brand, "branch", "--list"),
    )


def test_D1_round_trip_and_legacy(tmp_path):
    brand = _brand(tmp_path)
    loaded = questions.load_questions(brand)
    assert {q.id for q in loaded} == {"conflict.pages.doc.margin.top", "confirm.rule.titles-short", "gap.no-logo"}
    assert len(loaded) == 3
    q = next(q for q in loaded if q.id == "conflict.pages.doc.margin.top")
    assert q.recommended == "a"
    assert [o.id for o in q.options] == ["a", "b"]
    assert [e.crop for e in q.evidence] == ["crops/book-33.png", "crops/report-2.png"]
    path = brand / "theme/ingest/questions.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "questions": [
                    {
                        "id": "font.missing",
                        "kind": "font",
                        "text": "Supply font?",
                        "source": None,
                        "format": None,
                        "blocking": True,
                        "answer": None,
                        "answered_by": None,
                        "answered_at": None,
                    }
                ]
            }
        )
    )
    legacy = questions.load_questions(brand)
    assert len(legacy) == 1 and legacy[0].id == "font.missing"
    assert legacy[0].options == [] and legacy[0].evidence == []


@pytest.mark.parametrize("option, count", [("a", 0), ("b", 1)])
def test_D2_token_answer_and_departure(tmp_path, option, count):
    brand = _brand(tmp_path)
    result = answers.answer_question(brand, "conflict.pages.doc.margin.top", option=option)
    assert isinstance(result, answers.AnswerResult)
    assert result.question.option == option
    assert result.question.answer == ("20 mm (guidelines)" if option == "a" else "18 mm (examples)")
    assert result.question.answered_by == "owner"
    assert len(result.departures) == count
    if count:
        assert result.departures[0].path == "pages.doc.margin.top"
    theme = load_theme(brand / "theme")
    assert theme.tokens.pages["doc"].margin.top == pytest.approx(51.0236220472 if count else 56.6929133858)
    provenance = labels.token_label(theme, "pages.doc.margin.top")
    assert provenance.label == "answered" and provenance.source.question == "conflict.pages.doc.margin.top"
    assert run_git(brand, "branch", "--show-current").strip() == "main"
    assert run_git(brand, "status", "--porcelain") == ""
    record = changes.change_log(brand)[-1]
    assert record.what == "Answer conflict.pages.doc.margin.top" and record.formats == ["doc"]
    assert any(e.file == "materials/guidelines/book.pdf" and e.page == 33 for e in record.evidence)


@pytest.mark.parametrize("option", ["yes", "no"])
def test_D3_rule_or_record_only(tmp_path, option):
    brand = _brand(tmp_path)
    before = len(changes.change_log(brand))
    result = answers.answer_question(brand, "confirm.rule.titles-short", option=option)
    assert result.question.option == option and result.question.answer == ("Yes" if option == "yes" else "No")
    path = brand / "theme/rules/ingested/brand.titles-short.yaml"
    assert path.is_file() == (option == "yes")
    assert len(changes.change_log(brand)) == before + 1
    if option == "yes":
        rule = next(r for r in load_theme_rules(load_theme(brand / "theme")) if r.id == "brand.titles-short")
        assert rule.origin == "ingested" and rule.provenance.label == "answered"
        assert rule.provenance.source["question"] == "confirm.rule.titles-short"


def test_D4_free_text_records_change(tmp_path):
    brand = _brand(tmp_path)
    before = _files(brand / "theme")
    before.pop("ingest/questions.yaml")
    result = answers.answer_question(brand, "gap.no-logo", text="We have no logo; leave it out")
    assert result.question.answer == "We have no logo; leave it out" and result.question.option is None
    assert changes.change_log(brand)[-1].formats == ["slides", "doc"]
    after = _files(brand / "theme")
    after.pop("ingest/questions.yaml")
    assert after == before


@pytest.mark.parametrize("case", ["unknown", "already", "invalid_option", "empty", "text_only", "bad_rule"])
def test_D5_refusals_leave_brand_unchanged(tmp_path, case):
    brand = _brand(tmp_path)
    qid = "conflict.pages.doc.margin.top"
    kwargs = {"option": "a"}
    if case == "unknown":
        qid = "unknown"
    elif case == "already":
        answers.answer_question(brand, qid, option="a")
    elif case == "invalid_option":
        kwargs = {"option": "c"}
    elif case == "empty":
        kwargs = {}
    elif case == "text_only":
        kwargs = {"text": "Use this"}
    elif case == "bad_rule":
        qid = "invalid.rule"
        q = questions.BrandQuestion.model_validate(
            {
                "id": qid,
                "kind": "rule",
                "text": "Use rule?",
                "options": [
                    {"id": "yes", "label": "Yes", "effects": [{"kind": "write-rule", "rule": _rule("no-such-kind")}]}
                ],
            }
        )
        questions.add_questions(brand, [q])
        run_git(brand, "add", "-A")
        run_git(brand, "commit", "-m", "Add invalid rule question")
        kwargs = {"option": "yes"}
    before = _state(brand)
    with pytest.raises(BrandError):
        answers.answer_question(brand, qid, **kwargs)
    assert _state(brand) == before
    assert run_git(brand, "branch", "--show-current").strip() == "main"
