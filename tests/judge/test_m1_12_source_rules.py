# Intent: the two source rules report one finding per defect on the Document alone, with seeded fixtures.
from pathlib import Path

import pytest

from docla.source.parser import parse

try:
    from docla.checks import source as source_rules
except ImportError as error:
    if error.name not in ("docla.checks", "docla.checks.source"):
        raise
    source_rules = None

try:
    from docla.checks import engine
except ImportError as error:
    if error.name not in ("docla.checks", "docla.checks.engine"):
        raise
    engine = None

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects"
CITATIONS = "source.citations-resolve"
EMPTY = "source.empty-section"


def _require_interface() -> None:
    assert source_rules is not None and hasattr(source_rules, "RULES"), "docla.checks.source.RULES must exist"
    assert engine is not None and hasattr(engine, "run_checks"), "docla.checks.engine.run_checks must exist"
    assert hasattr(engine, "CheckContext"), "docla.checks.engine.CheckContext must exist"


def _rules(rule_id: str):
    _require_interface()
    return [rule for rule in source_rules.RULES if rule.id == rule_id]


def _run(rule_id: str, text: str):
    rules = _rules(rule_id)
    assert len(rules) == 1, f"RULES must hold exactly one {rule_id}"
    doc, _ = parse(text)
    return engine.run_checks(rules, engine.CheckContext(doc=doc))


def _fixture(rule_id: str, side: str) -> Path:
    path = FIXTURES / rule_id / side / "doc.md"
    assert path.is_file(), f"fixture {path} must exist"
    return path


def _doc(sections: str, sources: str = "- [S1] brief.pdf, p.1\n") -> str:
    return f"---\ndoctype: pitch-deck\nformat: slides\n---\n\n## Sources\n\n{sources}\n{sections}\n"


def test_D1_fail_fixture_gives_exactly_one_finding():
    findings = _run(CITATIONS, _fixture(CITATIONS, "fail").read_text())
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == CITATIONS
    assert finding.section_id is not None
    assert finding.measured["key"] in finding.message
    doc, _ = parse(_fixture(CITATIONS, "fail").read_text())
    listed = {source.key for source in doc.sources}
    assert finding.measured["key"] not in listed
    cited = {c.key for s in doc.sections if s.id == finding.section_id for i in s.items for c in i.citations}
    assert finding.measured["key"] in cited


def test_D1_pass_fixture_gives_no_finding():
    assert _run(CITATIONS, _fixture(CITATIONS, "pass").read_text()) == []


def test_D1_missing_key_is_reported_with_section_and_key():
    text = _doc(
        '::: {#aaaaa .section intent="x"}\n## One\n\n- Fine claim. [S1 p.2]\n:::\n\n'
        '::: {#bbbbb .section intent="x"}\n## Two\n\n- Bad claim. [S9 p.4]\n:::\n'
    )
    findings = _run(CITATIONS, text)
    assert [f.section_id for f in findings] == ["bbbbb"]
    assert findings[0].rule_id == CITATIONS
    assert findings[0].measured == {"key": "S9"}
    assert "S9" in findings[0].message


def test_D1_one_finding_per_missing_citation_across_sections():
    text = _doc(
        '::: {#aaaaa .section intent="x"}\n## One\n\n- Claim. [S7]\n:::\n\n'
        '::: {#bbbbb .section intent="x"}\n## Two\n\n- Claim. [S8]\n:::\n'
    )
    findings = _run(CITATIONS, text)
    assert sorted((f.section_id, f.measured["key"]) for f in findings) == [("aaaaa", "S7"), ("bbbbb", "S8")]


def test_D1_all_keys_listed_gives_no_finding():
    text = _doc(
        '::: {#aaaaa .section intent="x"}\n## One\n\n- Claim. [S1] [S2 p.3]\n:::\n',
        sources="- [S1] a.pdf\n- [S2] b.pdf\n",
    )
    assert _run(CITATIONS, text) == []


def test_D2_fail_fixture_gives_exactly_one_finding():
    text = _fixture(EMPTY, "fail").read_text()
    findings = _run(EMPTY, text)
    assert len(findings) == 1
    assert findings[0].rule_id == EMPTY
    doc, _ = parse(text)
    empty = [s.id for s in doc.sections if not (s.title or s.items or s.paragraphs or s.data or s.image)]
    assert empty == [findings[0].section_id]


def test_D2_pass_fixture_gives_no_finding():
    assert _run(EMPTY, _fixture(EMPTY, "pass").read_text()) == []


def test_D2_only_the_empty_section_is_reported():
    text = _doc(
        '::: {#aaaaa .section intent="x"}\n## Title only\n:::\n\n'
        '::: {#bbbbb .section intent="x"}\n:::\n\n'
        '::: {#ccccc .section intent="x"}\nA paragraph.\n:::\n'
    )
    findings = _run(EMPTY, text)
    assert [f.section_id for f in findings] == ["bbbbb"]
    assert findings[0].rule_id == EMPTY


@pytest.mark.parametrize(
    "body",
    [
        "- A bullet.",
        "A paragraph.",
        "```data\nkind: bar\n```",
    ],
)
def test_D2_any_content_makes_the_section_non_empty(body):
    text = _doc(f'::: {{#aaaaa .section intent="x"}}\n{body}\n:::\n')
    assert _run(EMPTY, text) == []


def test_D2_image_alone_makes_the_section_non_empty():
    text = _doc('::: {#aaaaa .section intent="x" image="photo.png"}\n:::\n')
    assert _run(EMPTY, text) == []


@pytest.mark.parametrize("rule_id", [CITATIONS, EMPTY])
def test_D3_rule_metadata(rule_id):
    (rule,) = _rules(rule_id)
    assert rule.tier == "source"
    assert rule.severity == "error"
    assert rule.status == "active"
    assert rule.remedy.class_ == "redraft"
    assert rule.origin == "manual"
    assert rule.strength == "hard"


def test_D3_rules_hold_exactly_the_two_source_rules():
    _require_interface()
    assert sorted(rule.id for rule in source_rules.RULES) == [CITATIONS, EMPTY]


def test_D3_both_rules_run_with_facts_none():
    _require_interface()
    text = _doc('::: {#aaaaa .section intent="x"}\n:::\n\n::: {#bbbbb .section intent="x"}\n## T\n\n- C. [S5]\n:::\n')
    doc, _ = parse(text)
    ctx = engine.CheckContext(doc=doc)
    assert ctx.facts is None
    findings = engine.run_checks(source_rules.RULES, ctx)
    assert sorted((f.rule_id, f.section_id) for f in findings) == [(CITATIONS, "bbbbb"), (EMPTY, "aaaaa")]
    assert all(f.tier == "source" and f.severity == "error" for f in findings)


@pytest.mark.parametrize("rule_id", [CITATIONS, EMPTY])
@pytest.mark.parametrize("side", ["fail", "pass"])
def test_D4_fixture_parses_without_error_findings(rule_id, side):
    _, findings = parse(_fixture(rule_id, side).read_text())
    assert [f.rule_id for f in findings if f.severity == "error"] == []
