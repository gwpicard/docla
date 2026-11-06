# Intent: titles are labels, enforced by a reusable source text-pattern check.
import runpy
from pathlib import Path

from docla import cli
from docla.checks import catalogue, engine, source
from docla.model import Document, Item, Provenance, Remedy, Rule, Section
from docla.source.parser import parse

ROOT = Path(__file__).resolve().parents[2]
SEEDED = ROOT / "tests" / "fixtures" / "seeded-defects"


def _title_rule():
    assert hasattr(catalogue, "all_rules"), "catalogue.all_rules must exist"
    rules = [rule for rule in catalogue.all_rules() if rule.id == "source.title-label"]
    assert len(rules) == 1, "source.title-label must exist exactly once"
    return rules[0]


def _check(rules, sections):
    assert "text-pattern" in engine.CHECKS, "text-pattern must be registered"
    return engine.run_checks(rules, engine.CheckContext(Document(front={}, format="slides", sections=sections)))


def _run(path, out, capsys):
    try:
        code = cli.main(["check", str(path), "--out", str(out)])
    except SystemExit as error:
        code = error.code
    return code, capsys.readouterr().out.splitlines()


def _pattern(field, regex, **condition):
    return Rule(
        id="test.pattern",
        title="Pattern",
        origin="manual",
        strength="hard",
        status="active",
        severity="error",
        tier="source",
        check={"kind": "text-pattern", "field": field, "regex": regex, **condition},
        remedy=Remedy.model_validate({"class": "redraft", "hint": "Rewrite"}),
        provenance=Provenance(source={"doc": "test"}),
    )


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
    prefix = m1 + source.M2_RULES
    assert rules[: len(prefix)] == prefix
    rule = _title_rule()
    assert rules.index(rule) >= len(prefix)
    assert (rule.title, rule.origin, rule.strength, rule.status) == (
        "A title is a label, not a question or a teaser",
        "manual",
        "hard",
        "active",
    )
    assert (rule.severity, rule.tier, rule.remedy.class_, rule.check["kind"]) == (
        "error",
        "source",
        "redraft",
        "text-pattern",
    )
    assert rule.scope.format is None
    assert rule.provenance.source == {"doc": "DESIGN.md", "section": "10.5"}


def test_D2_seeded_files_cli_and_engine(tmp_path, capsys):
    rule = _title_rule()
    assert "text-pattern" in engine.CHECKS, "text-pattern must be registered"
    for side, count, code in (("fail", 1, 1), ("pass", 0, 0)):
        path = SEEDED / "source.title-label" / side / "doc.md"
        assert path.is_file(), f"missing seeded fixture: {path}"
        doc, parsed = parse(path.read_text())
        assert parsed == []
        findings = engine.run_checks([rule], engine.CheckContext(doc))
        assert len(findings) == count
        if findings:
            assert findings[0].rule_id == "source.title-label"
            assert findings[0].measured == {"field": "title", "text": "What did the workshop find?"}
            assert "What did the workshop find?" in findings[0].message
        actual_code, lines = _run(path, tmp_path / side, capsys)
        assert actual_code == code
        if side == "fail":
            assert any(line.startswith("error source.title-label ") for line in lines)
        else:
            assert lines == ["no findings"]


def test_D3_title_endings_and_missing_title():
    sections = [
        Section(id=str(i), intent="statement", title=title)
        for i, title in enumerate(
            ["Next steps...", "Next steps…", "Why it works", "Is it? Yes, it works", None, "", "Question?  "]
        )
    ]
    findings = _check([_title_rule()], sections)
    assert [f.section_id for f in findings] == ["0", "1", "6"]
    assert [f.measured for f in findings] == [
        {"field": "title", "text": "Next steps..."},
        {"field": "title", "text": "Next steps…"},
        {"field": "title", "text": "Question?  "},
    ]
    assert all(
        text in finding.message
        for text, finding in zip(["Next steps...", "Next steps…", "Question?  "], findings, strict=True)
    )


def test_D4_paragraph_and_item_patterns():
    paragraphs = _pattern("paragraphs", "^[A-Z]", must_match=True)
    sections = [
        Section(id="bad", intent="body", paragraphs=["Good start", "lower case", "also lower"]),
        Section(id="good", intent="body", paragraphs=["First", "Second"]),
    ]
    findings = _check([paragraphs], sections)
    assert [(f.section_id, f.measured) for f in findings] == [("bad", {"field": "paragraphs", "text": "lower case"})]
    items = _pattern("items", "forbidden", must_not_match=True)
    sections = [
        Section(id="head", intent="bullets", items=[Item(head="forbidden head", body="Fine")]),
        Section(id="body", intent="bullets", items=[Item(head="Fine", body="A forbidden body")]),
        Section(id="sub", intent="bullets", items=[Item(body="Fine", sub=["forbidden sub"])]),
        Section(id="good", intent="bullets", items=[Item(head="Fine", body="Allowed", sub=["Also fine"])]),
    ]
    findings = _check([items], sections)
    assert [(f.section_id, f.measured) for f in findings] == [
        ("head", {"field": "items", "text": "forbidden head"}),
        ("body", {"field": "items", "text": "A forbidden body"}),
        ("sub", {"field": "items", "text": "forbidden sub"}),
    ]


def test_D5_existing_clean_inputs_and_geometry_failure(tmp_path, capsys):
    for judge in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        constants = runpy.run_path(str(ROOT / "tests" / "judge" / judge))
        for name in ("SLIDES", "DOC"):
            path = tmp_path / (judge + name + ".md")
            path.write_text(constants[name])
            code, lines = _run(path, tmp_path / (judge + name), capsys)
            assert (code, lines) == (0, ["no findings"])
    code, lines = _run(SEEDED / "geo.text-fits" / "fail" / "doc.md", tmp_path / "geo", capsys)
    assert code == 1
    assert any(line.startswith("error geo.text-fits ") for line in lines)
