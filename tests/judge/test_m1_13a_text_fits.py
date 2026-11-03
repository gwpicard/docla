# Intent: geo.text-fits reports a fixed frame whose content needs more height than it has, with per-item cut guidance.
from pathlib import Path

import pytest

try:
    from docla.checks import fit
except ImportError as error:
    if error.name != "docla.checks" and not str(error.name).startswith("docla.checks."):
        raise
    fit = None

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects" / "geo.text-fits"
RULE_ID = "geo.text-fits"


def _require_interface() -> None:
    assert fit is not None and hasattr(fit, "RULES"), "docla.checks.fit.RULES must exist"


def _rule():
    _require_interface()
    rules = [rule for rule in fit.RULES if rule.id == RULE_ID]
    assert len(rules) == 1, "RULES must hold exactly one geo.text-fits rule"
    return rules[0]


def _run(side: str, tmp_path: Path):
    _require_interface()
    text_path = FIXTURES / side / "doc.md"
    assert text_path.is_file(), f"fixture {text_path} must exist"
    from docla.checks.engine import CheckContext, run_checks
    from docla.facts.layout import layout_facts
    from docla.render.compose import assemble, compose

    from docla.render.typst import compile_pdf
    from docla.source.parser import parse

    doc, _ = parse(text_path.read_text())
    dest = tmp_path / "build"
    main = assemble(compose(doc), dest)
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, dest, pdf)
    facts = layout_facts(pdf, main, dest)
    findings = run_checks([_rule()], CheckContext(doc=doc, facts=facts))
    return doc, [f for f in findings if f.rule_id == RULE_ID]


def test_D1_fail_fixture_gives_one_finding_with_over(tmp_path):
    doc, findings = _run("fail", tmp_path)
    assert len(findings) == 1
    finding = findings[0]
    bullets = [s for s in doc.sections if s.intent == "bullets"]
    assert len(bullets) == 1
    assert finding.section_id == bullets[0].id
    measured = finding.measured
    assert measured["need"] > measured["have"]
    assert measured["over"] == pytest.approx(measured["need"] - measured["have"], abs=0.1)
    assert finding.severity == "error"
    assert finding.tier == "geometry"
    assert "pt" in finding.message


def test_D2_items_one_entry_per_item_in_order(tmp_path):
    doc, findings = _run("fail", tmp_path)
    assert len(findings) == 1
    section = next(s for s in doc.sections if s.intent == "bullets")
    items = findings[0].measured["items"]
    assert [entry["n"] for entry in items] == list(range(len(section.items)))
    for entry in items:
        assert set(entry) == {"n", "lines", "cut_to_save_line"}


def test_D2_one_line_and_wrapped_items(tmp_path):
    doc, findings = _run("fail", tmp_path)
    section = next(s for s in doc.sections if s.intent == "bullets")
    items = findings[0].measured["items"]
    one_line = [e for e in items if e["lines"] == 1]
    wrapped = [e for e in items if e["lines"] >= 2]
    assert one_line, "fail fixture must hold an item of one line"
    assert wrapped, "fail fixture must hold an item of two or more lines"
    for entry in one_line:
        assert entry["cut_to_save_line"] is None
    for entry in wrapped:
        item = section.items[entry["n"]]
        total = len(f"{item.head or ''} {item.body}".strip())
        assert 2 <= entry["cut_to_save_line"] <= total


def test_D3_pass_fixture_gives_no_finding(tmp_path):
    _, findings = _run("pass", tmp_path)
    assert findings == []


def test_D4_rule_metadata():
    rule = _rule()
    assert rule.tier == "geometry"
    assert rule.severity == "error"
    assert rule.remedy.class_ == "redraft"
    assert rule.status == "active"
    assert rule.scope.format == "slides"
