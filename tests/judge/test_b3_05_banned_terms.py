# Intent: The theme's banned words must not reach section titles, items or paragraphs.
import json
import re
import runpy
import shutil
from pathlib import Path

import pytest

from docla import cli
from docla.checks import catalogue, engine, source
from docla.model import Document, Item, Section, Source
from docla.source import parser
from docla.testing import golden
from docla.theme import neutral_theme
from docla.theme.voice import load_voice

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
JUDGES = Path(__file__).resolve().parent


def _rule():
    rules = [rule for rule in catalogue.all_rules() if rule.id == "source.banned-terms"]
    assert len(rules) == 1, "source.banned-terms must exist once in all_rules()"
    return rules[0]


def _run(path, tmp_path, capsys):
    try:
        code = cli.main(["check", str(path), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out.strip()


def test_D1_catalogue_order_and_rule_metadata():
    m1 = catalogue.m1_rules()
    assert [r.id for r in m1] == [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
    ]
    assert [r.id for r in source.RULES] == ["source.citations-resolve", "source.empty-section"]
    assert [r.id for r in source.M2_RULES] == ["source.intent-known"]
    rules = catalogue.all_rules()
    prefix = [*m1, *source.M2_RULES]
    assert rules[: len(prefix)] == prefix
    rule = _rule()
    assert rules.index(rule) >= len(prefix)
    assert (rule.severity, rule.tier, rule.remedy.class_) == ("error", "source", "redraft")
    assert (rule.title, rule.origin, rule.strength, rule.status) == (
        "Text uses no word the theme's voice bans",
        "manual",
        "hard",
        "active",
    )
    assert rule.scope.format is None
    assert rule.check == {"kind": "banned-terms"}


@pytest.mark.parametrize("kind, count, code", [("fail", 1, 1), ("pass", 0, 0)])
def test_D2_seeded_pair(kind, count, code, tmp_path, capsys):
    rule = _rule()
    path = FIXTURES / "seeded-defects" / "source.banned-terms" / kind / "doc.md"
    assert path.is_file(), f"missing seeded fixture: {path}"
    doc, parse_findings = parser.parse(path.read_text())
    assert parse_findings == []
    findings = engine.run_checks([rule], engine.CheckContext(doc, theme=neutral_theme()))
    assert len(findings) == count
    if count:
        assert findings[0].measured == {"field": "items", "terms": ["leverage"]}
        assert "leverage" in findings[0].message.lower()
    actual_code, out = _run(path, tmp_path, capsys)
    assert actual_code == code, out
    if count:
        assert any(
            line.startswith("error source.banned-terms ") and "leverage" in line.lower() for line in out.splitlines()
        )
    else:
        assert out == "no findings"


def test_D3_fields_boundaries_case_and_no_theme():
    rule = _rule()
    doc = Document(
        front={},
        format="slides",
        sources=[Source(key="S1", text="journey")],
        sections=[
            Section(id="title", intent="statement", title="Unlock the plan"),
            Section(id="paragraph", intent="body", paragraphs=["SYNERGY helps."]),
            Section(
                id="item",
                intent="bullets",
                items=[Item(head="Synergy", body="Leverage and unlock", sub=["journey and leverage"])],
            ),
            Section(
                id="safe",
                intent="bullets",
                items=[Item(body="leveraged")],
                note="journey",
                spoken="journey",
                source_line="journey",
            ),
        ],
    )
    findings = engine.run_checks([rule], engine.CheckContext(doc, theme=neutral_theme()))
    assert {(f.section_id, f.measured["field"], tuple(f.measured["terms"])) for f in findings} == {
        ("title", "title", ("unlock",)),
        ("paragraph", "paragraphs", ("synergy",)),
        ("item", "items", ("journey", "leverage", "synergy", "unlock")),
    }
    for finding in findings:
        assert all(term in finding.message.lower() for term in finding.measured["terms"])
    assert engine.run_checks([rule], engine.CheckContext(doc)) == []


def test_D4_existing_fixtures_and_timeline_golden(tmp_path, capsys):
    terms = load_voice(neutral_theme()).banned
    assert terms == ["leverage", "synergy", "unlock", "journey"]
    for path in (FIXTURES / "components" / "timeline.yaml", FIXTURES / "slides" / "gallery.md"):
        for term in terms:
            assert not re.search(r"\b" + re.escape(term) + r"\b", path.read_text(), re.IGNORECASE), (path, term)
    components = FIXTURES / "components"
    actual = golden.facts_for("timeline", components)
    expected = json.loads((components / "timeline.facts.json").read_text())
    assert golden.compare_facts(actual, expected) == []
    gallery = tmp_path / "gallery.md"
    shutil.copy(FIXTURES / "slides" / "gallery.md", gallery)
    code, out = _run(gallery, tmp_path, capsys)
    assert code == 0, out
    assert not any("source.banned-terms" in line for line in out.splitlines())


def test_D5_clean_documents_and_geometry_defect_still_check(tmp_path, capsys):
    for judge in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(JUDGES / judge))
        for name in ("SLIDES", "DOC"):
            path = tmp_path / (judge + name + ".md")
            path.write_text(examples[name])
            code, out = _run(path, tmp_path, capsys)
            assert (code, out) == (0, "no findings")
    path = FIXTURES / "seeded-defects" / "geo.text-fits" / "fail" / "doc.md"
    code, out = _run(path, tmp_path, capsys)
    assert code == 1
    assert any(line.startswith("error geo.text-fits ") for line in out.splitlines())
