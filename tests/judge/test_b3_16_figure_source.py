# Intent: figure source lines follow their figures and distant sources produce a warning.
import json
import runpy
from pathlib import Path

import pytest
import yaml

from docla import cli, source, theme
from docla.checks import catalogue, engine
from docla.checks import source as rule_source
from docla.facts.layout import LayoutFacts, layout_facts
from docla.model import Document, Section
from docla.render import compose, swatch, typst
from docla.render.marks import ElementMark
from docla.testing import golden

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/components"
SEEDED = ROOT / "tests/fixtures/seeded-defects/geo.figure-source"


def _rule():
    rules = [r for r in catalogue.all_rules() if r.id == "geo.figure-source"]
    assert len(rules) == 1, "geo.figure-source must be registered exactly once"
    return rules[0]


def _section(name):
    return Section.model_validate(yaml.safe_load((FIXTURES / f"{name}.yaml").read_text()))


def _doc(section):
    return Document(
        front={"doctype": "pitch-deck", "title": "Readout", "theme": "neutral"}, format="slides", sections=[section]
    )


def _render(section, path):
    path.mkdir(parents=True, exist_ok=True)
    return swatch.swatch(_doc(section), section.id, path, theme=theme.neutral_theme()).facts


def _check(path, out, capsys):
    try:
        code = cli.main(["check", str(path), "--out", str(out)])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    assert code == 0, (captured.out, captured.err)
    assert captured.out.strip() == "no findings"


def _mark(role, y, *, section="s1", page=1, h=10):
    return ElementMark(kind="element", role=role, id=section, page=page, x=20, y=y, w=100, h=h)


def _facts(marks):
    return LayoutFacts(pdf_sha256="", pages=[], words=[], shapes=[], marks=marks)


def test_D1_catalogue_rule_and_order():
    rule = _rule()
    assert (rule.tier, rule.severity, rule.remedy.class_) == ("geometry", "warning", "tune")
    assert getattr(rule.scope, "intents", None) is None
    assert getattr(rule.scope, "components", None) is None
    assert rule.check == {
        "kind": "adjacent",
        "a": {"role": "figure"},
        "b": {"role": "figure-source"},
        "within_pt": 24,
        "edge": "bottom",
    }
    assert [r.id for r in catalogue.m1_rules()] == [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
    ]
    assert [r.id for r in rule_source.RULES] == ["source.citations-resolve", "source.empty-section"]
    ids = [r.id for r in catalogue.all_rules()]
    assert all(ids.index(r.id) < ids.index(rule.id) for r in [*catalogue.m1_rules(), *rule_source.M2_RULES])


def test_D2_synthetic_gaps_and_edge():
    rule = _rule()
    figure = _mark("figure", 100, h=100)
    for intent in ("chart", "table", "statement"):
        doc = _doc(Section(id="s1", intent=intent))

        def run(marks, selected=rule, document=doc):
            return engine.run_checks([selected], engine.CheckContext(document, _facts(marks)))

        findings = run([figure, _mark("figure-source", 230)])
        assert len(findings) == 1
        finding = findings[0]
        assert (finding.section_id, finding.page, finding.severity) == ("s1", 1, "warning")
        assert finding.measured == {"gap_pt": 30, "within_pt": 24}
        assert (finding.region.x, finding.region.y, finding.region.w, finding.region.h) == (20, 230, 100, 10)
        assert "30" in finding.message and "24" in finding.message
        assert run([figure, _mark("figure-source", 220)]) == []
        assert run([figure, _mark("figure-source", 150)]) == []
        assert run([figure]) == []
        assert run([_mark("figure-source", 230)]) == []
        bad = rule.model_copy(update={"check": {**rule.check, "edge": "left"}})
        with pytest.raises(ValueError, match="left"):
            run([figure, _mark("figure-source", 230)], bad)


def test_D3_seeded_fail(tmp_path):
    rule = _rule()
    fixture = SEEDED / "fail/main.typ"
    assert fixture.is_file(), "seeded fail main.typ must exist"
    doc = _doc(Section(id="s1", intent="chart"))
    kit = tmp_path / "kit"
    main = compose.assemble(compose.compose(doc), kit, theme=theme.neutral_theme())
    main.write_text(fixture.read_text())
    fonts = compose.font_paths(kit)
    pdf = tmp_path / "fixture.pdf"
    typst.compile_pdf(main, kit, pdf, fonts)
    facts = layout_facts(pdf, main, kit, font_paths=fonts)
    findings = [
        f
        for f in engine.run_checks([rule], engine.CheckContext(doc, facts, theme=theme.neutral_theme()))
        if f.rule_id == rule.id
    ]
    assert len(findings) == 1
    assert (findings[0].section_id, findings[0].severity) == ("s1", "warning")
    assert findings[0].measured["gap_pt"] > 24


def test_D4_seeded_pass_and_chart_check(tmp_path, capsys):
    path = SEEDED / "pass/doc.md"
    assert path.is_file(), "seeded pass doc.md must exist"
    _check(path, tmp_path / "pass-out", capsys)
    chart = tmp_path / "chart.md"
    chart.write_text(source.serialise(_doc(_section("chart"))))
    _check(chart, tmp_path / "chart-out", capsys)


def test_D5_table_geometry_and_golden(tmp_path):
    section = _section("table")
    facts = _render(section, tmp_path)
    marks = [m for m in facts.marks if isinstance(m, ElementMark) and m.id == section.id]
    figures = [m for m in marks if m.role == "figure"]
    sources = [m for m in marks if m.role == "figure-source"]
    assert len(figures) == len(sources) == 1
    figure, line = figures[0], sources[0]
    assert line.page == figure.page
    assert 0 <= line.y - (figure.y + figure.h) <= 24
    assert (
        engine.run_checks(catalogue.all_rules(), engine.CheckContext(_doc(section), facts, theme=theme.neutral_theme()))
        == []
    )
    expected = json.loads((FIXTURES / "table.facts.json").read_text())
    assert golden.compare_facts(golden.facts_for("table", FIXTURES), expected) == []


def test_D6_clean_texts_and_table_capacity(tmp_path, capsys):
    for pattern in ("test_m1_17*.py", "test_m2_theme_in_builds.py"):
        paths = list((ROOT / "tests/judge").glob(pattern))
        assert len(paths) == 1
        texts = runpy.run_path(str(paths[0]))
        for key in ("SLIDES", "DOC"):
            path = tmp_path / f"{paths[0].stem}-{key}.md"
            path.write_text(texts[key])
            _check(path, tmp_path / f"{paths[0].stem}-{key}-out", capsys)
    _table_capacity_and_content_depth(tmp_path)


def _table_capacity_and_content_depth(tmp_path):
    section = _section("table")
    data = {"columns": [f"Col {n}" for n in range(1, 7)], "rows": [["Value"] * 6 for _ in range(10)]}
    for count in (10, 11):
        data["rows"] = [["Value"] * 6 for _ in range(count)]
        facts = _render(section.model_copy(update={"data": data}), tmp_path / str(count))
        fits = [m for m in facts.marks if m.kind == "fit"]
        assert fits
        assert all(m.ok for m in fits) if count == 10 else any(not m.ok for m in fits)
    facts = _render(section, tmp_path / "fixture")
    title = [w.box.y1 for w in facts.words if w.role == "title"]
    body = [w.box.y1 for w in facts.words if w.role != "title"]
    assert title and body
    assert max(body) >= (max(title) + 500) / 2
