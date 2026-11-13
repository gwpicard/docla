# The intake brief records a report's intent, provenance and current state.
import datetime
import importlib.util
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

try:
    import docla.model.brief as subject
except ImportError as error:
    if error.name != "docla.model.brief" or importlib.util.find_spec("docla.model.brief") is not None:
        raise
    subject = None

from docla.model.schema import export_schemas
from docla.server.docs import document_names

FIELDS = ("doctype", "audience", "key_message", "ask", "scope", "topics", "metrics", "comparisons", "findings", "sensitivities", "exclusions", "tone", "length", "required_elements", "open_risks")
SCHEMAS = Path(__file__).resolve().parents[2] / "docs" / "schemas"


def interface():
    assert subject is not None, "docla.model.brief must exist"
    for name in ("Brief", "Audience", "Ask", "BriefScope", "Topic", "Metric", "Comparisons", "BriefFinding", "Sensitivity", "Tone", "Length", "RequiredElement", "FieldProvenance", "BRIEF_FIELDS", "BRIEF_SUFFIX", "brief_path", "load_brief", "save_brief", "BriefError", "export_brief_schema"):
        assert hasattr(subject, name), f"docla.model.brief.{name} must exist"
    return subject


def example(m):
    return m.Brief(
        format="slides", request="a sales report for last quarter for the board, focusing on the initiatives and profitability",
        doctype="board-report", audience=m.Audience(who="board", prior_knowledge="sales", decision="approve continued funding of the partner channel"),
        ask=m.Ask(kind="decide", text="approve funding"),
        scope=m.BriefScope(period="Q3 FY26", entities=["group"], currency="GBP", data_exclusions=["draft"]),
        topics=[m.Topic(name=n, data_ref="Sales!A2:A9", include=True, order=i, role="area") for i, n in enumerate(["partner", "direct", "online", "retail"])],
        metrics=[m.Metric(name="profit", definition="revenue less costs", sources=["F3a9c01b2d4"], caveats="estimated")],
        comparisons=m.Comparisons(primary="budget", secondary=["prior year"]),
        findings=[m.BriefFinding(claim="profit grew", evidence=["F3a9c01b2d4"], importance="lead", explanation="higher sales")],
        sensitivities=[m.Sensitivity(item="discounts", why="confidential", presentation="aggregate")], exclusions=["names"],
        tone=m.Tone(register="measured", person="institutional", detail="summary"),
        length=m.Length(count=12, figures="mixed", appendix=True, deadline=datetime.date(2026, 12, 1), delivery="pre-read"),
        required_elements=[m.RequiredElement(element="summary", source="doctype:board-report")], open_risks=["board has not seen the discount plan"],
        provenance={"audience": m.FieldProvenance(status="confirmed", person="owner"), "scope": m.FieldProvenance(status="inferred", evidence=["F3a9c01b2d4"]), "key_message": m.FieldProvenance(status="skipped"), "tone": m.FieldProvenance(status="defaulted", evidence=["doctype:board-report"])},
    )


def test_D1_defaults_fields_and_round_trip():
    m = interface()
    b = m.Brief(format="slides")
    assert m.BRIEF_FIELDS == FIELDS
    assert set(m.Brief.model_fields) == set(FIELDS) | {"schema_version", "format", "request", "provenance"}
    assert b.schema_version == 1 and b.request == ""
    for name in ("doctype", "audience", "key_message", "ask", "comparisons", "tone"):
        assert getattr(b, name) is None
    for name in ("topics", "metrics", "findings", "sensitivities", "exclusions", "required_elements", "open_risks"):
        assert getattr(b, name) == []
    assert b.provenance == {}
    full = example(m)
    assert m.Brief.model_validate_json(full.model_dump_json()) == full


def test_D2_validation_and_status():
    m = interface()
    for data in ({}, {"format": "pdf"}, {"format": "slides", "provenance": {"colour": {"status": "confirmed"}}}, {"format": "slides", "provenance": {"scope": {"status": "guessed"}}}, {"format": "slides", "provenance": {"scope": {"status": "inferred"}}}, {"format": "slides", "ask": {"kind": "approve"}}, {"format": "slides", "findings": [{"claim": "x", "importance": "key"}]}, {"format": "slides", "length": {"count": 0}}, {"format": "slides", "initiatives": []}):
        with pytest.raises(ValidationError):
            m.Brief.model_validate(data)
    b = m.Brief.model_validate({"format": "slides", "provenance": {"scope": {"status": "inferred", "evidence": ["F3a9c01b2d4"]}, "key_message": {"status": "skipped"}, "audience": {"status": "confirmed", "person": "owner"}}})
    assert b.status("key_message") == "skipped"
    assert b.status("scope") == "inferred" and b.provenance["scope"].evidence == ["F3a9c01b2d4"]
    assert b.provenance["audience"].person == "owner" and b.status("metrics") is None
    with pytest.raises(ValueError):
        b.status("colour")


def test_D3_storage_and_errors(tmp_path):
    m = interface()
    deck = tmp_path / "deck.md"
    deck.write_text("---\ntitle: Deck\n---\n", encoding="utf-8")
    path = tmp_path / "deck.brief.json"
    assert m.BRIEF_SUFFIX == ".brief.json" and m.brief_path(deck) == path
    assert m.load_brief(deck) is None
    b = example(m)
    assert m.save_brief(deck, b) == path
    expected = (b.model_dump_json(indent=2) + "\n").encode("utf-8")
    assert path.read_bytes() == expected and b"\r" not in path.read_bytes()
    assert m.load_brief(deck) == b
    assert m.save_brief(deck, b) == path and path.read_bytes() == expected
    assert sorted(p.name for p in tmp_path.iterdir()) == ["deck.brief.json", "deck.md"]
    assert document_names(tmp_path) == ["deck"]
    for contents in ('{"format": "slides", "ask": {"kind": "approve"}}', "not json"):
        path.write_text(contents, encoding="utf-8")
        with pytest.raises(m.BriefError, match=r"deck\.brief\.json"):
            m.load_brief(deck)


def test_D4_format_length_and_storage(tmp_path):
    m = interface()
    slides = example(m)
    doc = m.Brief.model_validate({**slides.model_dump(), "format": "doc"})
    assert doc.length.count == 12
    assert doc.model_dump(exclude={"format"}) == slides.model_dump(exclude={"format"})
    assert doc.length_unit() == "pages" and slides.length_unit() == "slides"
    report = tmp_path / "report.md"
    assert m.save_brief(report, doc) == tmp_path / "report.brief.json"
    assert m.load_brief(report) == doc


def test_D5_schema_export_and_existing_schemas(tmp_path):
    m = interface()
    destination = tmp_path / "brief"
    path = m.export_brief_schema(destination)
    assert path == destination / "Brief.schema.json"
    assert list(destination.iterdir()) == [path]
    expected = (json.dumps(m.Brief.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    assert path.read_bytes() == expected
    committed = SCHEMAS / "brief" / "Brief.schema.json"
    assert committed.is_file(), "committed brief schema must exist"
    assert path.read_bytes() == committed.read_bytes()
    assert {"format", "provenance"} <= json.loads(path.read_bytes())["properties"].keys()
    names = ["Document.schema.json", "Finding.schema.json", "Patch.schema.json", "Rule.schema.json"]
    assert sorted(p.name for p in export_schemas(tmp_path / "existing")) == names
    assert sorted(p.name for p in SCHEMAS.glob("*.schema.json")) == names
