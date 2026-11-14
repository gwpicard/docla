# Intent: cited numbers must match the gathered facts for their cited sources and places.
import asyncio
import importlib
import importlib.util
import inspect
import shutil
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from docla import cli
from docla.agents.gatherer import Fact
from docla.checks import catalogue, engine
from docla.loop import micro
from docla.model import Citation, Document, Item, Section
from docla.theme import neutral_theme


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name == name and importlib.util.find_spec(name) is None:
            return None
        raise


numbers = _optional("docla.checks.numbers")
SEEDED = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects" / "source.number-in-source"


def _facts():
    assert {"kind", "value", "unit"} <= set(Fact.model_fields), "numeric Fact fields must exist"
    return [
        Fact(
            text="North, Revenue: £1,234,500",
            source_key="S2",
            locator="Sales!B2",
            kind="currency",
            value=Decimal("1234500"),
            unit="GBP",
        ),
        Fact(
            text="North, Margin: 12.5%",
            source_key="S2",
            locator="Sales!C2",
            kind="percent",
            value=Decimal("12.5"),
            unit="%",
        ),
    ]


def _doc(text, locator="Sales!B2", fmt="slides"):
    return Document(
        front={"doctype": "pitch-deck"},
        format=fmt,
        sections=[
            Section(
                id="s1",
                intent="bullets",
                title="Revenue",
                items=[Item(body=text, citations=[Citation(key="S2", locator=locator)])],
            )
        ],
    )


def _rule():
    rules = [rule for rule in catalogue.all_rules() if rule.id == "source.number-in-source"]
    assert len(rules) == 1, "source.number-in-source must be registered once"
    return rules[0]


def _check(doc, facts):
    assert "source_facts" in inspect.signature(engine.CheckContext).parameters, "CheckContext must accept source_facts"
    return engine.run_checks([_rule()], engine.CheckContext(doc, source_facts=facts))


def test_D1_rounding_and_written_numbers():
    assert numbers is not None, "docla.checks.numbers must exist"
    assert hasattr(numbers, "within_rounding") and hasattr(numbers, "written_numbers")
    for written, value, expected in [
        ("12%", "12.5", True),
        ("13%", "12.5", True),
        ("12.5%", "12.5", True),
        ("1,234,500", "1234500", True),
        ("-5%", "5", True),
        ("12.4%", "12.5", False),
        ("1,234,000", "1234500", False),
        ("1,300,000", "1234500", False),
    ]:
        assert numbers.within_rounding(written, Decimal(value)) is expected
    assert numbers.written_numbers("In 2026 revenue rose 12.5% to £1,234,500") == ["12.5%", "1,234,500"]


def test_D2_catalogue_and_source_check():
    rule = _rule()
    assert (rule.tier, rule.severity, rule.remedy.class_) == ("source", "error", "redraft")
    facts = _facts()
    wrong = _doc("Revenue reached £1,300,000")
    right = _doc("Revenue reached £1,234,500")
    findings = _check(wrong, facts)
    assert len(findings) == 1
    assert findings[0].section_id == "s1"
    assert findings[0].measured["number"] == "1,300,000"
    assert findings[0].measured["citations"] == ["S2 Sales!B2"]
    assert _check(right, facts) == []
    assert _check(wrong, None) == []
    assert _check(right, None) == []


def test_D3_locator_rounding_percent_and_format():
    facts = _facts()
    cases = [
        ("The margin was 12%", "Sales!C2", 0),
        ("The margin was 12.5%", "Sales!B2", 1),
        ("The margin was 12.5%", None, 0),
        ("Revenue reached 1,234,500%", "Sales!B2", 1),
        ("Revenue was 1,300,000 and margin 30%", "Sales!B2", 2),
    ]
    for text, locator, count in cases:
        for fmt in ("slides", "doc"):
            findings = _check(_doc(text, locator, fmt), facts)
            assert len(findings) == count, (text, fmt, findings)
            if count == 2:
                assert len({finding.fingerprint for finding in findings}) == 2


def _cli(args, capsys):
    try:
        code = cli.main(args)
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out


def test_D4_seeded_pair_and_missing_facts(tmp_path, capsys):
    for kind, expected in (("fail", 1), ("pass", 0)):
        folder = SEEDED / kind
        assert (folder / "doc.md").is_file() and (folder / "facts.json").is_file(), f"missing seeded {kind} fixture"
        root = tmp_path / kind
        root.mkdir()
        doc = root / "doc.md"
        shutil.copy(folder / "doc.md", doc)
        facts_path = root / ".docla" / "write" / "doc" / "facts.json"
        facts_path.parent.mkdir(parents=True)
        shutil.copy(folder / "facts.json", facts_path)
        code, output = _cli(["check", str(doc), "--out", str(root / "out")], capsys)
        assert code == expected, output
        if kind == "fail":
            assert "source.number-in-source" in output
            facts_path.unlink()
            _, output = _cli(["check", str(doc), "--out", str(root / "without")], capsys)
            assert "source.number-in-source" not in output
        else:
            assert output.strip() == "no findings"


def test_D5_micro_evaluate_uses_source_facts(tmp_path):
    assert "source_facts" in inspect.signature(micro.LoopContext).parameters, "LoopContext must accept source_facts"
    facts = _facts()
    doc = _doc("Revenue reached £1,300,000")
    job = SimpleNamespace(section_id="s1", format="slides")
    for source_facts, expected in ((facts, True), (None, False)):
        ctx = micro.LoopContext(doc, neutral_theme(), tmp_path, object(), source_facts=source_facts)
        state = asyncio.run(micro.evaluate(doc.sections[0], job, ctx, tag="a03"))
        assert ("source.number-in-source" in [f.rule_id for f in state.findings]) is expected


def test_D5_clean_existing_documents_print_no_findings(tmp_path, capsys):
    from test_m1_17_cli_build_check import DOC, SLIDES

    for name, text in (("slides", SLIDES), ("doc", DOC)):
        path = tmp_path / f"{name}.md"
        path.write_text(text)
        code, output = _cli(["check", str(path), "--out", str(tmp_path / f"out-{name}")], capsys)
        assert code == 0
        assert output.strip() == "no findings"
