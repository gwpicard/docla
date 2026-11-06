# Intent: report missing-fact markers as draft warnings and final errors.
import importlib
import importlib.util
import runpy
from pathlib import Path

import pytest

from docla import cli
from docla.checks import catalogue, engine, source
from docla.model import Document, Item, Section
from docla.source import parser

try:
    gaps = importlib.import_module("docla.checks.gaps")
except ImportError as error:
    if error.name != "docla.checks.gaps" or importlib.util.find_spec("docla.checks.gaps") is not None:
        raise
    gaps = None

ROOT = Path(__file__).resolve().parents[1]
SEEDED = ROOT / "fixtures" / "seeded-defects"


def _rules():
    assert gaps is not None and hasattr(gaps, "RULES"), "docla.checks.gaps.RULES must exist"
    return gaps.RULES


def _check(doc, final=False):
    rules = _rules()
    assert "final" in engine.CheckContext.__dataclass_fields__, "CheckContext.final must exist"
    return engine.run_checks(rules, engine.CheckContext(doc, final=final))


def _run(path, out, capsys, final=False):
    args = ["check", str(path), "--out", str(out)]
    if final:
        args.append("--final")
    try:
        code = cli.main(args)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
    captured = capsys.readouterr()
    return code, captured.out


def test_D1_catalogue_order_and_rule_metadata():
    expected = [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
        "source.intent-known",
    ]
    assert [rule.id for rule in catalogue.m1_rules()] == expected[:6]
    assert len(source.RULES) == 2
    rules = catalogue.all_rules()
    ids = [rule.id for rule in rules]
    assert ids[:7] == expected
    assert ids.count("source.gap-present") == 1
    index = ids.index("source.gap-present")
    assert all(index > ids.index(rule.id) for rule in [*catalogue.m1_rules(), *source.M2_RULES])
    rule = rules[index]
    assert (rule.severity, rule.tier, rule.remedy.class_) == ("warning", "source", "report")
    assert (rule.origin, rule.strength, rule.status, rule.check) == (
        "manual",
        "hard",
        "active",
        {"kind": "gap-present"},
    )
    assert rule.title and rule.remedy.hint
    assert rule.provenance.source == {"doc": "DESIGN.md", "section": "10.5"}


def test_D2_seeded_pair_draft_and_final():
    _rules()
    for side in ("fail", "pass"):
        path = SEEDED / "source.gap-present" / side / "doc.md"
        assert path.is_file(), f"missing seeded fixture {path}"
        doc, parse_findings = parser.parse(path.read_text())
        assert parse_findings == []
        assert len(doc.sections) == 1
        for final in (False, True):
            findings = _check(doc, final)
            if side == "pass":
                assert findings == []
            else:
                assert len(findings) == 1
                finding = findings[0]
                assert (finding.rule_id, finding.severity, finding.section_id, finding.measured) == (
                    "source.gap-present",
                    "error" if final else "warning",
                    doc.sections[0].id,
                    {"gaps": ["the yearly saving"]},
                )
                assert "the yearly saving" in finding.message and "1" in finding.message


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"title": "Before [GAP: title fact] after"}, ["title fact"]),
        ({"paragraphs": ["Before [GAP: paragraph fact] after"]}, ["paragraph fact"]),
        ({"note": "[GAP: note fact]"}, ["note fact"]),
        ({"data": {"rows": [{"nested": [0, {"value": "[GAP: data fact]"}]}]}}, ["data fact"]),
        ({"items": [Item(head="[GAP: head]", body="[GAP: body]", sub=["[GAP: sub]"])]}, ["head", "body", "sub"]),
        (
            {"code": ["[GAP: code]"], "spoken": "[GAP: spoken]", "source_line": "[GAP: source]"},
            ["code", "spoken", "source"],
        ),
        ({"title": "[GAP: first] and [GAP: second]"}, ["first", "second"]),
    ],
)
def test_D3_section_text_fields_and_order(fields, expected):
    section = Section(id="abcde", intent="body", **fields)
    doc = Document(front={}, format="doc", sections=[section])
    findings = _check(doc)
    assert len(findings) == 1
    assert findings[0].section_id == "abcde"
    assert findings[0].measured == {"gaps": expected}
    assert expected[0] in findings[0].message
    assert str(len(expected)) in findings[0].message


def test_D4_cli_seeded_pair(tmp_path, capsys):
    for side in ("fail", "pass"):
        path = SEEDED / "source.gap-present" / side / "doc.md"
        assert path.is_file(), f"missing seeded fixture {path}"
        doc, _ = parser.parse(path.read_text())
        assert len(doc.sections) == 1 and doc.sections[0].id
        for final in (False, True):
            code, out = _run(path, tmp_path / f"{side}-{final}", capsys, final)
            lines = [line for line in out.splitlines() if "source.gap-present" in line]
            if side == "pass":
                assert code == 0 and lines == [], out
            else:
                assert code == (1 if final else 0), out
                prefix = f"{'error' if final else 'warning'} source.gap-present {doc.sections[0].id} "
                assert len(lines) == 1 and lines[0].startswith(prefix), out


def test_D5_existing_clean_documents_and_geometry_failure(tmp_path, capsys):
    for filename in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(ROOT / "judge" / filename))
        for name in ("SLIDES", "DOC"):
            path = tmp_path / f"{filename}-{name}.md"
            path.write_text(examples[name])
            code, out = _run(path, tmp_path / f"out-{filename}-{name}", capsys)
            assert (code, out.strip()) == (0, "no findings")
    fixture = SEEDED / "geo.text-fits" / "fail" / "doc.md"
    code, out = _run(fixture, tmp_path / "out-geometry", capsys)
    assert code == 1
    assert any(line.startswith("error geo.text-fits ") for line in out.splitlines()), out
