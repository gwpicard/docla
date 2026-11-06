# Intent: declarative selectors and boolean checks compose registered rules without changing existing behaviour.
import dataclasses
import importlib
import importlib.util
import runpy
from pathlib import Path

import pytest

from docla import cli
from docla.checks import catalogue, engine, source
from docla.facts.layout import LayoutFacts, PlacedShape, PlacedWord
from docla.facts.models import FactBox
from docla.model import Document, Provenance, Remedy, Rule, Section
from docla.render.compose import ComposedSection, Composition

try:
    dsl = importlib.import_module("docla.checks.dsl")
except ImportError as error:
    if error.name != "docla.checks.dsl" or importlib.util.find_spec("docla.checks.dsl") is not None:
        raise
    dsl = None


def _require_dsl():
    assert dsl is not None, "docla.checks.dsl must exist"
    assert hasattr(dsl, "select") and hasattr(dsl, "Selected")
    return dsl


def _context(*, composition=True, facts=True):
    assert "composition" in {f.name for f in dataclasses.fields(engine.CheckContext)}
    doc = Document(
        front={}, format="slides", sections=[Section(id="a", intent="statement"), Section(id="b", intent="bullets")]
    )
    box = FactBox(page=1, x0=0, y0=0, x1=10, y1=10)
    words = [
        PlacedWord(
            text=text, font="Inter", size=12, colour="#000000", box=box, baseline=9, role=role, section_id=section
        )
        for text, role, section in [("A", "title", "a"), ("B", "item", "b"), ("C", "title", "b"), ("loose", None, None)]
    ]
    shapes = [
        PlacedShape(kind="rect", fill=None, stroke=None, box=box, role="panel", section_id=s) for s in ("a", "b", None)
    ]
    layout = LayoutFacts(pdf_sha256="0" * 64, pages=[], words=words, shapes=shapes, marks=[])
    comp = Composition(
        format="slides",
        sections=[
            ComposedSection(id="a", component="statement", props={}),
            ComposedSection(id="b", component="bullets", props={}),
        ],
    )
    return engine.CheckContext(doc=doc, facts=layout if facts else None, composition=comp if composition else None)


def _rule(kind, checks, tier="source"):
    return Rule(
        id="judge.boolean",
        title="Boolean",
        origin="manual",
        strength="soft",
        status="active",
        severity="warning",
        tier=tier,
        check={"kind": kind, "checks": checks},
        remedy=Remedy(**{"class": "tune", "hint": "fix"}),
        provenance=Provenance(),
    )


def test_D1_text_selection_preserves_order_and_metadata():
    module = _require_dsl()
    ctx = _context()
    selected = module.select(ctx, {"kind": "text", "role": "title"})
    assert [(x.kind, x.role, x.section_id, x.fact.text) for x in selected] == [
        ("text", "title", "a", "A"),
        ("text", "title", "b", "C"),
    ]
    assert all(isinstance(x, module.Selected) for x in selected)
    assert dataclasses.is_dataclass(selected[0]) and selected[0].__dataclass_params__.frozen
    assert [x.fact.text for x in module.select(ctx, {"kind": "text", "role": ["title", "item"]})] == ["A", "B", "C"]
    assert module.select(_context(facts=False), {"kind": "text"}) == []


def test_D2_component_and_intent_filters():
    module = _require_dsl()
    ctx = _context()
    assert [x.section_id for x in module.select(ctx, {"kind": "shape", "component": "bullets"})] == ["b"]
    assert [x.fact.text for x in module.select(ctx, {"kind": "text", "section_intent": "statement"})] == ["A"]
    assert [x.fact.text for x in module.select(ctx, {"kind": "text", "component": "any"})] == ["A", "B", "C", "loose"]
    assert module.select(_context(composition=False), {"kind": "text", "component": "bullets"}) == []
    assert [
        x.fact.text
        for x in module.select(ctx, {"kind": "text", "section_intent": ["bullets"], "component": ["bullets"]})
    ] == ["B", "C"]
    assert module.select(_context(facts=False), {"kind": "shape"}) == []


def test_D3_section_selection_returns_section_itself():
    module = _require_dsl()
    ctx = _context()
    selected = module.select(ctx, {"kind": "section", "component": "bullets"})
    assert len(selected) == 1
    assert isinstance(selected[0], module.Selected)
    assert (selected[0].kind, selected[0].section_id, selected[0].role) == ("section", "b", None)
    assert selected[0].fact is ctx.doc.sections[1]


def test_D4_boolean_checks_and_source_tier():
    _require_dsl()
    for name in ("not", "all-of", "any-of"):
        assert name in engine.CHECKS, f"{name} must be registered by the catalogue"

    @engine.register("judge-b3-02-hit-a")
    class HitA:
        tier = "geometry"

        def run(self, ctx, rule):
            return [engine.make_finding(rule, ctx, message="first", section_id="a")]

    @engine.register("judge-b3-02-hit-b")
    class HitB:
        tier = "geometry"

        def run(self, ctx, rule):
            return [engine.make_finding(rule, ctx, message="second", section_id="b")]

    @engine.register("judge-b3-02-empty")
    class Empty:
        tier = "geometry"

        def run(self, ctx, rule):
            return []

    hit_a, hit_b, empty = ({"kind": name} for name in ("judge-b3-02-hit-a", "judge-b3-02-hit-b", "judge-b3-02-empty"))
    ctx = _context(facts=False)
    assert engine.run_checks([_rule("not", [hit_a])], ctx) == []
    inverted = engine.run_checks([_rule("not", [empty])], ctx)
    assert len(inverted) == 1
    assert (inverted[0].rule_id, inverted[0].severity, inverted[0].section_id) == ("judge.boolean", "warning", None)
    assert "judge-b3-02-empty" in inverted[0].message
    findings = engine.run_checks([_rule("all-of", [hit_a, hit_b])], ctx)
    assert [(f.rule_id, f.severity, f.section_id, f.message) for f in findings] == [
        ("judge.boolean", "warning", "a", "first"),
        ("judge.boolean", "warning", "b", "second"),
    ]
    assert engine.run_checks([_rule("any-of", [empty, hit_a])], ctx) == []
    assert [f.section_id for f in engine.run_checks([_rule("any-of", [hit_a, hit_b])], ctx)] == ["a", "b"]
    with pytest.raises(engine.UnknownCheckError):
        engine.run_checks([_rule("all-of", [{"kind": "judge-b3-02-unknown"}])], ctx)


def test_D5_catalogue_order_and_existing_rules():
    assert [r.id for r in source.RULES] == ["source.citations-resolve", "source.empty-section"]
    assert [r.id for r in catalogue.m1_rules()] == [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
    ]
    assert [r.id for r in source.M2_RULES] == ["source.intent-known"]
    assert catalogue.all_rules()[:7] == [*catalogue.m1_rules(), *source.M2_RULES]


def test_D6_clean_cli_inputs_report_exactly_no_findings(tmp_path, capsys):
    folder = Path(__file__).parent
    for filename in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(folder / filename))
        for name in ("SLIDES", "DOC"):
            path = tmp_path / f"{filename}-{name}.md"
            path.write_text(examples[name])
            try:
                code = cli.main(["check", str(path), "--out", str(tmp_path / f"out-{filename}-{name}")])
            except SystemExit as error:
                code = error.code
            output = capsys.readouterr()
            assert code == 0, output.err
            assert output.out.splitlines() == ["no findings"]
