# Intent: Reconcile brand evidence into settled values, questions and proposed rules.
import importlib
import importlib.util
import re
from pathlib import Path

import pytest
import yaml

from docla.brand.git import run_git
from docla.brand.workspace import BrandError, init_brand

try:
    reconcile_module = importlib.import_module("docla.brand.reconcile")
except ImportError as error:
    if error.name != "docla.brand.reconcile" or importlib.util.find_spec("docla.brand.reconcile") is not None:
        raise
    reconcile_module = None


def subject():
    assert reconcile_module is not None, "docla.brand.reconcile must exist"
    for name in ("reconcile", "load_reconciliation", "Reconciliation"):
        assert hasattr(reconcile_module, name), f"reconcile.{name} must exist"
    return reconcile_module


def write_model(brand, name, model):
    directory = brand / "theme/ingest"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(model.model_dump_json(indent=2) + "\n")


@pytest.fixture
def brand(tmp_path):
    if reconcile_module is None:
        return None
    from docla.brand.measure import Measurement
    from docla.brand.tokenmap import TokenClaims

    brand = init_brand("acme", tmp_path / ".brand")
    source = {"file": "materials/guidelines/book.pdf", "page": 33, "quote": "Margins are 20 mm", "found": "text"}
    claims = TokenClaims.model_validate({"items": [
        {"path": "pages.doc.margin.top", "value": 56.69, "format": "doc", "claim_id": "c-2", "strength": "hard", "source": source, "reason": "stated margin"},
        {"path": "type.scale.doc.body.size", "value": 11, "format": "doc", "claim_id": "c-3", "strength": "hard", "source": {**source, "page": 12, "quote": "Body 11 pt"}, "reason": "stated size"},
    ], "refused": [], "untied": []})
    write_model(brand, "token-claims.json", claims)

    def stat(value, low=None, high=None, n=4):
        return {"value": value, "min": value if low is None else low, "max": value if high is None else high, "n": n}

    def measured(fmt, file, width, height, margins, body, title, titles):
        return {"kind": "examples", "format": fmt, "pages": [{"file": file, "page": i + 1} for i in range(4)],
                "width": stat(width), "height": stat(height), "margin": margins,
                "title_size": stat(title), "body_size": stat(body), "smallest_size": stat(body),
                "title_font": None, "body_font": None, "text_colours": [], "fill_colours": [],
                "words_per_page": stat(20), "titles": [{"file": file, "page": i + 1, "text": text, "size": title} for i, text in enumerate(titles)]}

    doc = measured("doc", "materials/examples/report.pdf", 595.28, 841.89,
                   {"top": stat(51, 49.6, 52.4), "left": stat(70.9), "right": stat(70.9), "bottom": stat(56.69)}, 11, 16, [])
    slides = measured("slides", "materials/examples/deck.pdf", 960, 540,
                      {"top": stat(40), "left": stat(50, 48, 52), "right": stat(48), "bottom": stat(40)}, 20, 36,
                      ["Sales grew strongly", "Costs held", "Margins rose", "Next steps"])
    write_model(brand, "measure.json", Measurement.model_validate({"sets": [doc, slides], "skipped": []}))
    return brand


def values(result):
    return {item.path: item for item in result.values}


def questions(brand):
    data = yaml.safe_load((brand / "theme/ingest/questions.yaml").read_text())
    entries = data if isinstance(data, list) else data["questions"]
    return {entry["id"]: entry for entry in entries}


def test_D1_agreement_provenance_and_formats(brand):
    result = subject().reconcile(brand)
    items = values(result)
    body = items["type.scale.doc.body.size"]
    assert (body.status, body.value, body.provenance.source.role, body.provenance.source.page) == ("agreed", 11, "guidelines", 12)
    assert all(item.provenance.label == "measured" for item in result.values)
    assert all(item.format == "doc" for item in result.values if item.path.startswith("pages.doc."))
    assert all(item.format == "slides" for item in result.values if item.path.startswith("pages.slides."))
    assert [item.path for item in result.values] == sorted(item.path for item in result.values)


def test_D2_conflict_keeps_strongest_source_and_offers_values(brand):
    item = values(subject().reconcile(brand))["pages.doc.margin.top"]
    assert (item.status, item.value, item.drift, item.question) == ("conflict", 56.69, False, "conflict.pages.doc.margin.top")
    question = questions(brand)[item.question]
    assert (question["kind"], question["format"], question["blocking"], question["recommended"]) == ("conflict", "doc", True, "a")
    a, b = question["options"]
    assert (a["id"], b["id"]) == ("a", "b")
    assert "guidelines" in a["label"] and "page 33" in a["label"] and "examples" in b["label"]
    assert a["effects"][0]["value"] == 56.69 and b["effects"][0]["value"] == 51.0
    assert any(e["page"] == 33 for e in question["evidence"])


def test_D3_example_only_values_are_proposed(brand):
    item = values(subject().reconcile(brand))["type.scale.slides.body.size"]
    assert (item.status, item.value) == ("proposed", 20)
    question = questions(brand)["confirm.type.scale.slides.body.size"]
    assert question["kind"] == "confirm" and question["blocking"] is False
    assert [option["id"] for option in question["options"]] == ["yes", "no"]
    assert question["options"][0]["effects"][0]["value"] == 20
    assert question["options"][1]["effects"] == []


def test_D4_proposed_title_rules_and_confirmation(brand):
    subject()
    from docla.model import Rule
    from docla.theme.labels import check_rule_label

    rules = subject().reconcile(brand).proposed_rules
    assert [r.id for r in rules] == ["brand.slides.title-no-full-stop", "brand.slides.title-words"]
    for proposal in rules:
        rule = Rule.model_validate(proposal.rule_data())
        assert (rule.strength, rule.status, rule.scope.format, rule.provenance.label) == ("soft", "proposed", "slides", "measured")
        check_rule_label(rule, labelled=True)
    pattern = rules[1].check["regex"]
    assert re.search(pattern, "Costs held")
    assert not re.search(pattern, "Sales grew very strongly")
    option = questions(brand)["confirm.rule.brand.slides.title-words"]["options"][0]
    assert option["id"] == "yes" and option["effects"][0]["kind"] == "write-rule"
    assert option["effects"][0]["rule"]["status"] == "active"


def test_D5_persistence_and_missing_input(brand, tmp_path):
    module = subject()
    result = module.reconcile(brand)
    output = brand / "theme/ingest/reconcile.json"
    store = brand / "theme/ingest/questions.yaml"
    saved, saved_questions = output.read_bytes(), store.read_bytes()
    assert saved.endswith(b"\n")
    assert module.Reconciliation.model_validate_json(saved) == result == module.load_reconciliation(brand)
    assert module.reconcile(brand) == result
    assert output.read_bytes() == saved and store.read_bytes() == saved_questions
    empty = init_brand("empty", tmp_path / "empty-root")
    with pytest.raises(BrandError, match="docla brand reconcile"):
        module.load_reconciliation(empty)
    with pytest.raises(BrandError):
        module.reconcile(empty)


def test_D5_cli_and_design(brand, capsys):
    subject()
    from docla.cli import main

    run_git(brand, "add", "-A")
    run_git(brand, "commit", "-m", "Prepare evidence")
    assert main(["brand", "reconcile", "acme", "--root", str(brand.parent)]) == 0
    assert "conflict" in capsys.readouterr().out
    assert run_git(brand, "branch", "--show-current").strip() == "main"
    assert run_git(brand, "status", "--porcelain") == ""
    empty = init_brand("empty", brand.parent)
    assert main(["brand", "reconcile", "empty", "--root", str(brand.parent)]) == 2
    assert run_git(empty, "status", "--porcelain") == ""
    design = (Path(__file__).resolve().parents[2] / "docs/DESIGN.md").read_text()
    assert "measured only from examples" in design
    assert "measured from a template the brand supplied" in design
