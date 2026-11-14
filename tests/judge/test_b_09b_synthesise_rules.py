# Intent: Turn brand claims into validated rules and rubric questions.
import asyncio
import importlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

import docla
from docla.agents.client import Claude
from docla.brand.workspace import init_brand
from docla.config import ProjectConfig
from docla.testing.fakes import FakeTransport, fake_response
from docla.theme import load_theme, neutral_theme
from docla.theme.rubric import load_rubric
from docla.theme.rules import load_theme_rules


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not str(error.name).startswith(name + "."):
            raise
        if importlib.util.find_spec(error.name) is not None:
            raise
        return None


synth = _module("docla.brand.synth_rules")
agents = _module("docla.brand.agents")


def _api():
    assert synth is not None, "docla.brand.synth_rules must exist"
    assert hasattr(synth, "valid_check"), "valid_check must exist"
    assert hasattr(synth, "synthesise_rules"), "synthesise_rules must exist"
    return synth


def test_D1_brand_model_and_unchanged_defaults():
    assert agents is not None and hasattr(agents, "brand_models"), "brand_models must exist"
    config = ProjectConfig()
    assert config.models == {
        "writer": "claude-sonnet-5-5",
        "critic": "claude-opus-5-5",
        "diagnose": "claude-opus-5-5",
        "triage": "claude-haiku-4-5",
    }
    assert agents.brand_models(config).get("brand.synthesise") == "claude-opus-5-5"
    assert (
        agents.brand_models(ProjectConfig(models={"critic": "critic-model", "brand.synthesise": "custom"})).get(
            "brand.synthesise"
        )
        == "custom"
    )


def test_D2_valid_checks_include_nested_specs():
    api = _api()
    check = {"kind": "text-pattern", "field": "title", "regex": r"\.\s*$", "must_match": False}
    assert api.valid_check(check) is None
    assert api.valid_check({"kind": "all-of", "checks": [check]}) is None
    assert api.valid_check({"kind": "any-of", "checks": [check]}) is None
    assert api.valid_check({"kind": "not", "checks": [check]}) is None


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"kind": "logo-aspect"},
        {"kind": "text-pattern", "field": "title", "regex": "([", "must_match": False},
        {"kind": "text-pattern", "field": "unknown", "regex": "a", "must_match": True},
        {"kind": "text-pattern", "field": "title", "regex": "a", "must_match": "false"},
        {"kind": "all-of", "checks": [{"kind": "logo-aspect"}]},
    ],
)
def test_D2_invalid_checks_are_rejected(bad):
    assert isinstance(_api().valid_check(bad), str)


class Ledger:
    def add(self, role, model, usage):
        return 0


def _fixture(tmp_path):
    _api()
    claims = importlib.import_module("docla.brand.claims")
    brand = init_brand("acme", tmp_path / ".brand")
    theme = brand / "theme"
    shutil.rmtree(theme)
    shutil.copytree(Path(docla.__file__).resolve().parent / "themes/neutral", theme)
    info = yaml.safe_load((theme / "theme.yaml").read_text())
    info["labelled"] = True
    (theme / "theme.yaml").write_text(yaml.safe_dump(info, sort_keys=False))
    inferred = {"label": "inferred", "source": {"note": "docla neutral value"}}
    labels = {
        "tokens": {
            key: inferred
            for key in (
                "colour.roles",
                "colour.chart",
                "colour.usage",
                "colour.contrast_min",
                "type.families",
                "type.scale",
                "pages.slides",
                "pages.doc",
                "spacing.unit",
                "spacing.scale",
                "imagery.min_dpi",
            )
        },
        "rubric": {item.id: inferred for item in load_rubric(neutral_theme()).items},
    }
    (theme / "provenance.yaml").write_text(yaml.safe_dump(labels, sort_keys=False))
    rows = [
        ("c-1", "token", "colour", "Brand blue", "hard", [], 0.9, False),
        ("c-10", "rule", "typography", "Slide titles never end with a full stop.", "hard", ["slides"], 0.9, False),
        ("c-11", "rule", "typography", "Headings are always in sentence case.", "hard", [], 0.4, False),
        ("c-12", "recommended", "imagery", "Photography should feel warm and natural.", "soft", [], 0.9, False),
        ("c-13", "forbidden", "logo", "Never stretch the logo.", "hard", [], 0.9, False),
        ("c-14", "rule", "typography", "Use short paragraphs.", "soft", [], 0.9, False),
        ("c-15", "rule", "typography", "Avoid exclamation marks.", "soft", [], 0.9, False),
        ("c-16", "rule", "imagery", "Crop photos to a square.", "soft", [], 0.9, True),
    ]
    data = [
        {
            "id": i,
            "kind": k,
            "topic": t,
            "statement": s,
            "strength": strength,
            "formats": formats,
            "confidence": confidence,
            "illustrative": illustrative,
            "illustrative_reason": "shown" if illustrative else None,
            "values": [],
            "check_hint": None,
            "sources": [
                {
                    "file": "materials/guidelines/book.pdf",
                    "page": 4,
                    "quote": s,
                    "found": "text",
                    "visual": False,
                    "bbox": None,
                }
            ],
        }
        for i, k, t, s, strength, formats, confidence, illustrative in rows
    ]
    field = "claims" if "claims" in claims.ClaimSet.model_fields else "items"
    claimset = claims.ClaimSet.model_validate({field: data})
    ingest = theme / "ingest"
    ingest.mkdir(exist_ok=True)
    (ingest / "claims.json").write_text(claimset.model_dump_json(indent=2) + "\n")
    return brand


def _fake(count=1):
    pattern = {"kind": "text-pattern", "field": "title", "regex": r"\.\s*$", "must_match": False}

    def draft(ident, title, tier, check=None, question=None):
        return {
            "claim_id": ident,
            "title": title,
            "tier": tier,
            "severity": "error",
            "check_json": json.dumps(check) if check is not None else None,
            "question": question,
            "remedy_class": "redraft",
            "remedy_hint": "Revise the page",
        }

    reply = {
        "drafts": [
            draft("c-10", "Titles have no full stop", "source", pattern),
            draft("c-11", "Headings use sentence case", "source", pattern),
            draft("c-12", "Use warm photography", "semantic", question="Do the photographs feel warm and natural?"),
            draft("c-13", "Do not stretch the logo", "source", {"kind": "logo-aspect"}),
            draft("c-15", "Avoid exclamation marks", "source", {**pattern, "regex": "(["}),
        ]
    }
    transport = FakeTransport({"syn": [fake_response(json.dumps(reply)) for _ in range(count)]})
    return Claude(
        transport, Ledger(), {"brand.segment": "seg", "brand.extract": "ext", "brand.synthesise": "syn"}
    ), transport


def _run(brand, claude):
    return asyncio.run(_api().synthesise_rules(brand, claude))


def test_D1_claims_are_sent_once(tmp_path):
    brand = _fixture(tmp_path)
    claude, transport = _fake()
    _run(brand, claude)
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request["model"] == "syn"
    text = json.dumps([request["system"], request["messages"]])
    assert all(value in text for value in ("c-10", "c-15", "text-pattern"))
    assert "c-16" not in text
    assert 'c-1\\"' not in json.dumps(request["messages"])


def test_D2_claim_becomes_scoped_rule(tmp_path):
    brand = _fixture(tmp_path)
    _run(brand, _fake()[0])
    rules = load_theme_rules(load_theme(brand / "theme"))
    rule = next(
        r
        for r in rules
        if r.provenance.source and r.provenance.source.get("quote") == "Slide titles never end with a full stop."
    )
    assert rule.id.startswith("brand.typography.")
    assert (rule.strength, rule.status, rule.scope.format, rule.check["kind"], rule.provenance.label) == (
        "hard",
        "active",
        "slides",
        "text-pattern",
        "measured",
    )
    assert not any(
        r.provenance.source
        and r.provenance.source.get("quote")
        in {"Photography should feel warm and natural.", "Never stretch the logo.", "Avoid exclamation marks."}
        for r in rules
    )


def test_D3_rubric_items_and_labels(tmp_path):
    brand = _fixture(tmp_path)
    _run(brand, _fake()[0])
    items = load_rubric(load_theme(brand / "theme")).items
    labels = yaml.safe_load((brand / "theme/provenance.yaml").read_text())["rubric"]
    for text in ("Do the photographs feel warm and natural?", "Never stretch the logo.", "Avoid exclamation marks."):
        item = next(item for item in items if text in item.question)
        assert item.id.startswith("sem.") and labels[item.id]["label"] == "measured"
    for item in load_rubric(neutral_theme()).items:
        assert any(actual.id == item.id for actual in items)
        assert labels[item.id]["label"] == "inferred"


def test_D4_low_confidence_and_unplaced(tmp_path):
    brand = _fixture(tmp_path)
    _run(brand, _fake()[0])
    questions = importlib.import_module("docla.brand.questions").load_questions(brand)
    rules = load_theme_rules(load_theme(brand / "theme"))
    rule = next(
        r
        for r in rules
        if r.provenance.source and r.provenance.source.get("quote") == "Headings are always in sentence case."
    )
    confirmation = next(q for q in questions if q.id == "rule.confirm." + rule.id)
    assert (confirmation.kind, confirmation.blocking, confirmation.recommended) == ("rule", True, "keep")
    assert [option.id for option in confirmation.options] == ["keep", "soften"]
    assert confirmation.options[0].effects == []
    effect = confirmation.options[1].effects[0]
    assert effect.kind == "write-rule" and effect.rule.strength == "soft"
    unplaced = next(q for q in questions if q.id == "rule.unplaced.c-14")
    assert unplaced.blocking is False and "Use short paragraphs." in unplaced.text


def test_D5_repeat_is_byte_identical(tmp_path):
    brand = _fixture(tmp_path)
    claude, _ = _fake(2)
    _run(brand, claude)
    theme = brand / "theme"

    def snapshot():
        paths = list((theme / "rules/ingested").glob("*.yaml")) + [
            theme / "rubric/visual.yaml",
            theme / "provenance.yaml",
        ]
        return {p.relative_to(theme): p.read_bytes() for p in paths}

    before = snapshot()
    _run(brand, claude)
    assert snapshot() == before
