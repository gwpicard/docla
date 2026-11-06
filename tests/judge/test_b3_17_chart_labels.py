# Intent: chart labels stay aligned with their marks and mark lengths reflect the data.
import importlib
import importlib.util
import runpy
import shutil
from pathlib import Path

import pytest
import yaml

from docla import cli
from docla.checks import catalogue, engine, source
from docla.facts.layout import LayoutFacts, layout_facts
from docla.facts.models import PageFacts
from docla.model import Document, Section
from docla.render import compose
from docla.render.kit import lib_dir
from docla.render.marks import ElementMark
from docla.render.typst import compile_pdf
from docla.source.serialiser import serialise
from docla.theme import neutral_theme

ROOT = Path(__file__).resolve().parents[2]
SEEDED = ROOT / "tests/fixtures/seeded-defects/geo.chart-labels"
CHART = ROOT / "tests/fixtures/components/chart.yaml"

try:
    charts = importlib.import_module("docla.checks.charts")
except ImportError as error:
    if error.name != "docla.checks.charts" or importlib.util.find_spec("docla.checks.charts") is not None:
        raise
    charts = None


def _rule():
    assert charts is not None and hasattr(charts, "RULES"), "docla.checks.charts.RULES must exist"
    matches = [rule for rule in charts.RULES if rule.id == "geo.chart-labels"]
    assert len(matches) == 1
    return matches[0]


def _doc(section=None):
    return Document(
        front={"doctype": "pitch-deck", "title": "Chart"},
        format="slides",
        sections=[section or Section(id="s1", intent="chart")],
    )


def _check(doc, facts, composition=None):
    rule = _rule()
    if composition is None:
        ctx = engine.CheckContext(doc=doc, facts=facts, theme=neutral_theme())
    else:
        assert "composition" in engine.CheckContext.__dataclass_fields__, "CheckContext must accept composition"
        ctx = engine.CheckContext(doc=doc, facts=facts, theme=neutral_theme(), composition=composition)
    return [f for f in engine.run_checks([rule], ctx) if f.rule_id == "geo.chart-labels"]


def _run(path, out, capsys):
    try:
        code = cli.main(["check", str(path), "--out", str(out)])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_catalogue_rule_and_order():
    rule = _rule()
    rules = catalogue.all_rules()
    assert len(charts.RULES) == 1
    assert [r.id for r in rules].count("geo.chart-labels") == 1
    assert rules.index(rule) >= len(catalogue.m1_rules()) + len(source.M2_RULES)
    assert rules[: len(catalogue.m1_rules())] == catalogue.m1_rules()
    assert [r.id for r in source.RULES] == ["source.citations-resolve", "source.empty-section"]
    assert (rule.tier, rule.severity, rule.remedy.class_) == ("geometry", "error", "engine")
    assert rule.check == {"kind": "chart-labels", "tolerance_pt": 4, "length_tolerance_pt": 1}
    assert (rule.title, rule.origin, rule.strength, rule.status) == (
        "Chart labels sit by their marks and bars match their values",
        "manual",
        "hard",
        "active",
    )
    assert rule.remedy.hint


def test_D2_seeded_drift_finding(tmp_path):
    _rule()
    fixture = SEEDED / "fail/main.typ"
    assert fixture.is_file(), "the seeded fail fixture must exist"
    root = tmp_path / "render"
    root.mkdir()
    shutil.copytree(lib_dir(), root / "lib")
    main = root / "main.typ"
    main.write_text(fixture.read_text())
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, root, pdf)
    findings = _check(_doc(), layout_facts(pdf, main, root))
    assert len(findings) == 1
    finding = findings[0]
    assert hasattr(finding, "role"), "findings must expose their role"
    assert (finding.section_id, finding.severity, finding.role) == ("s1", "error", "chart-label")
    assert finding.measured["off_pt"] >= 36


def test_D3_seeded_pass_cli(tmp_path, capsys):
    fixture = SEEDED / "pass/doc.md"
    assert fixture.is_file(), "the seeded pass fixture must exist"
    code, out, err = _run(fixture, tmp_path / "out", capsys)
    assert code == 0, out + err
    assert "geo.chart-labels" not in out


def test_D4_rendered_chart_and_changed_values(tmp_path):
    _rule()
    section = Section.model_validate(yaml.safe_load(CHART.read_text()))
    doc = _doc(section)
    composition = compose.compose(doc)
    root = tmp_path / "render"
    main = compose.assemble(composition, root, theme=neutral_theme())
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, root, pdf, font_paths=compose.font_paths(root))
    facts = layout_facts(pdf, main, root)
    assert _check(doc, facts, composition) == []
    changed = composition.model_copy(deep=True)
    assert changed.sections[0].content["data"]["series"][0]["values"][0] == 4
    changed.sections[0].content["data"]["series"][0]["values"][0] = 8
    findings = _check(doc, facts, changed)
    assert findings and all(hasattr(f, "role") for f in findings), "findings must expose their role"
    assert any(f.role == "chart-mark" for f in findings)


def test_D5_axis_alignment_and_drift():
    def facts(label_y):
        marks = [
            ElementMark(kind="element", id="s1", role="chart-mark", page=1, x=160, y=100, w=380, h=12),
            ElementMark(kind="element", id="s1", role="chart-label", page=1, x=40, y=label_y, w=48, h=12),
        ]
        return LayoutFacts(
            pdf_sha256="0" * 64,
            pages=[PageFacts(page=1, width=960, height=540, words=[], shapes=[])],
            words=[],
            shapes=[],
            marks=marks,
        )

    assert _check(_doc(), facts(100)) == []
    hits = _check(_doc(), facts(152))
    assert len(hits) == 1
    assert hasattr(hits[0], "role"), "findings must expose their role"
    assert (hits[0].section_id, hits[0].role, hits[0].page) == ("s1", "chart-label", 1)
    assert hits[0].measured["off_pt"] >= 40
    assert (hits[0].region.x, hits[0].region.y, hits[0].region.w, hits[0].region.h) == (40, 152, 48, 12)


@pytest.mark.parametrize(
    "judge,name",
    [
        ("test_m1_17_cli_build_check.py", "SLIDES"),
        ("test_m1_17_cli_build_check.py", "DOC"),
        ("test_m2_theme_in_builds.py", "SLIDES"),
        ("test_m2_theme_in_builds.py", "DOC"),
    ],
)
def test_D6_clean_texts(judge, name, tmp_path, capsys):
    text = runpy.run_path(str(ROOT / "tests/judge" / judge))[name]
    path = tmp_path / "input.md"
    path.write_text(text)
    code, out, err = _run(path, tmp_path / "out", capsys)
    assert code == 0, out + err
    assert out.splitlines() == ["no findings"]


def test_D6_chart_deck_is_clean(tmp_path, capsys):
    section = Section.model_validate(yaml.safe_load(CHART.read_text()))
    path = tmp_path / "deck.md"
    path.write_text(serialise(_doc(section)))
    code, out, err = _run(path, tmp_path / "out", capsys)
    assert code == 0, out + err
    assert out.splitlines() == ["no findings"]
