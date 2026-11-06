# Intent: final checks reject uncited item figures while draft checks remain silent.
import importlib.util
import inspect
import runpy
from pathlib import Path

import pytest

from docla import cli
from docla.checks import catalogue, engine, source
from docla.model import Citation, Document, Item, Section
from docla.source import parser

try:
    import docla.checks.figures as figures
except ImportError as error:
    if error.name != "docla.checks.figures" or importlib.util.find_spec("docla.checks.figures") is not None:
        raise
    figures = None

ROOT = Path(__file__).resolve().parents[1]
SEEDED = ROOT / "fixtures" / "seeded-defects"
FIXTURE = SEEDED / "source.uncited-figure"


def _rules():
    assert figures is not None and hasattr(figures, "RULES"), "docla.checks.figures.RULES must exist"
    return figures.RULES


def _check(doc, final=True):
    rules = _rules()
    assert "final" in inspect.signature(engine.CheckContext).parameters, "CheckContext.final must exist"
    return engine.run_checks(rules, engine.CheckContext(doc, final=final))


def _fixture(kind):
    path = FIXTURE / kind / "doc.md"
    assert path.is_file(), f"seeded {kind} fixture must exist: {path}"
    doc, findings = parser.parse(path.read_text())
    assert findings == []
    return path, doc


def _run(args, capsys):
    try:
        code = cli.main(args)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
    output = capsys.readouterr()
    return code, output.out


def test_D1_catalogue_rule_order_and_metadata():
    expected = [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
        "source.intent-known",
    ]
    rules = catalogue.all_rules()
    ids = [rule.id for rule in rules]
    assert [rule.id for rule in catalogue.m1_rules()] == expected[:6]
    assert len(source.RULES) == 2
    assert ids[:7] == expected
    assert ids.count("source.uncited-figure") == 1
    index = ids.index("source.uncited-figure")
    assert all(ids.index(rule.id) < index for rule in [*catalogue.m1_rules(), *source.M2_RULES])
    rule = rules[index]
    assert (rule.severity, rule.tier, rule.remedy.class_) == ("error", "source", "redraft")
    assert (rule.origin, rule.strength, rule.status, rule.check) == (
        "manual",
        "hard",
        "active",
        {"kind": "uncited-figure"},
    )
    assert rule.title and rule.remedy.hint


def test_D2_seeded_pair():
    _, fail = _fixture("fail")
    _, passed = _fixture("pass")
    assert len(fail.sections) == 1
    findings = _check(fail)
    assert len(findings) == 1
    finding = findings[0]
    assert (finding.rule_id, finding.severity, finding.section_id) == (
        "source.uncited-figure",
        "error",
        fail.sections[0].id,
    )
    assert finding.measured == {"numbers": ["12%"]}
    assert "12%" in finding.message
    assert _check(passed) == []


def test_D2_item_scope_and_order():
    doc = Document(
        front={},
        format="slides",
        sections=[
            Section(
                id="first",
                intent="bullets",
                items=[
                    Item(head="42%", body="Dropped 12% of readings."),
                    Item(body="Another 7 readings."),
                    Item(body="Cited 99%.", citations=[Citation(key="S1")]),
                    Item(body="No figure.", sub=["88%"]),
                ],
                paragraphs=["Paragraph 77%."],
            ),
            Section(id="second", intent="bullets", items=[Item(body="Only 3 readings.")]),
            Section(
                id="ignored",
                intent="bullets",
                paragraphs=["55%"],
                items=[
                    Item(body="No figure", sub=["66%"]),
                    Item(head="44%", body="Cited", citations=[Citation(key="S1")]),
                ],
            ),
        ],
    )
    findings = _check(doc)
    assert [(f.section_id, f.severity, f.measured) for f in findings] == [
        ("first", "error", {"numbers": ["42%", "12%", "7"]}),
        ("second", "error", {"numbers": ["3"]}),
    ]
    assert "42%" in findings[0].message


def test_D3_draft_is_silent(tmp_path, capsys):
    path, doc = _fixture("fail")
    assert engine.run_checks(_rules(), engine.CheckContext(doc)) == []
    code, out = _run(["check", str(path), "--out", str(tmp_path / "out")], capsys)
    assert code == 0
    assert "source.uncited-figure" not in out


def test_D4_final_cli_seeded_pair(tmp_path, capsys):
    fail_path, doc = _fixture("fail")
    pass_path, _ = _fixture("pass")
    assert len(doc.sections) == 1 and doc.sections[0].id
    code, out = _run(["check", str(fail_path), "--final", "--out", str(tmp_path / "fail")], capsys)
    assert code == 1
    assert any(line.startswith(f"error source.uncited-figure {doc.sections[0].id} ") for line in out.splitlines())
    code, out = _run(["check", str(pass_path), "--final", "--out", str(tmp_path / "pass")], capsys)
    assert code == 0
    assert "source.uncited-figure" not in out


@pytest.mark.parametrize("judge", ["test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"])
@pytest.mark.parametrize("name", ["SLIDES", "DOC"])
def test_D5_clean_existing_texts(judge, name, tmp_path, capsys):
    text = runpy.run_path(str(ROOT / "judge" / judge))[name]
    path = tmp_path / "clean.md"
    path.write_text(text)
    code, out = _run(["check", str(path), "--out", str(tmp_path / "out")], capsys)
    assert code == 0
    assert out.splitlines() == ["no findings"]


@pytest.mark.parametrize("rule_id", ["geo.text-fits", "geo.in-safe-area"])
def test_D5_existing_geometry_pass_fixtures(rule_id, tmp_path, capsys):
    path = SEEDED / rule_id / "pass" / "doc.md"
    code, out = _run(["check", str(path), "--out", str(tmp_path / "out")], capsys)
    assert code == 0, out


def test_D5_existing_text_fits_failure(tmp_path, capsys):
    path = SEEDED / "geo.text-fits" / "fail" / "doc.md"
    code, out = _run(["check", str(path), "--out", str(tmp_path / "out")], capsys)
    assert code == 1
    assert any(line.startswith("error geo.text-fits ") for line in out.splitlines())
