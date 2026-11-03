# Intent: geo.in-safe-area and geo.min-font flag content outside the margins and text below the minimum size.
import importlib
import shutil
from pathlib import Path

from docla.model import Document, Section
from docla.render.kit import lib_dir
from docla.render.typst import compile_pdf
from docla.source.parser import parse

SEEDED = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects"


def _optional(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if not name.startswith("docla.") or not (module_name == name or module_name.startswith(name + ".")):
            raise
        return None


bounds = _optional("docla.checks.bounds")
engine = _optional("docla.checks.engine")
layout = _optional("docla.facts.layout")
compose = _optional("docla.render.compose")


def _require_interface() -> None:
    assert bounds is not None and hasattr(bounds, "RULES"), "docla.checks.bounds.RULES must exist"
    assert engine is not None and hasattr(engine, "run_checks"), "docla.checks.engine.run_checks must exist"
    assert engine is not None and hasattr(engine, "CheckContext"), "docla.checks.engine.CheckContext must exist"
    assert layout is not None and hasattr(layout, "layout_facts"), "docla.facts.layout.layout_facts must exist"
    assert compose is not None and hasattr(compose, "assemble"), "docla.render.compose.assemble must exist"


def _rule(rule_id: str):
    _require_interface()
    matches = [r for r in bounds.RULES if r.id == rule_id]
    assert len(matches) == 1, f"bounds.RULES must hold exactly one rule {rule_id}"
    return matches[0]


def _check(doc: Document, facts, rule_id: str):
    ctx = engine.CheckContext(doc=doc, facts=facts)
    return [f for f in engine.run_checks([_rule(rule_id)], ctx) if f.rule_id == rule_id]


def _facts_from_fixture(side_dir: Path, tmp_path: Path) -> tuple[Document, object]:
    _require_interface()
    assert side_dir.is_dir(), f"fixture folder {side_dir} must exist"
    root = tmp_path / "render"
    pdf = tmp_path / "out.pdf"
    working_file = side_dir / "doc.md"
    typ_source = side_dir / "main.typ"
    if working_file.exists():
        doc, _ = parse(working_file.read_text())
        main = compose.assemble(compose.compose(doc), root)
    else:
        assert typ_source.exists(), f"{side_dir} must hold doc.md or main.typ"
        root.mkdir()
        shutil.copytree(lib_dir(), root / "lib")
        main = root / "main.typ"
        main.write_text(typ_source.read_text())
        doc = Document(front={}, format="slides", sections=[Section(id="s1", intent="statement")])
    compile_pdf(main, root, pdf)
    return doc, layout.layout_facts(pdf, main, root)


def test_D1_in_safe_area_fail_fixture_is_flagged(tmp_path):
    doc, facts = _facts_from_fixture(SEEDED / "geo.in-safe-area" / "fail", tmp_path)
    findings = _check(doc, facts, "geo.in-safe-area")
    assert findings, "the overflowing callout must give a geo.in-safe-area finding"
    callout_ids = {s.id for s in doc.sections if s.intent == "callout"}
    assert callout_ids, "the fail fixture must hold a callout section"
    assert {f.section_id for f in findings} <= callout_ids
    assert any(f.measured["count"] >= 1 and f.measured["max_outside_pt"] > 1 for f in findings)


def test_D1_in_safe_area_pass_fixture_is_clean(tmp_path):
    doc, facts = _facts_from_fixture(SEEDED / "geo.in-safe-area" / "pass", tmp_path)
    assert _check(doc, facts, "geo.in-safe-area") == []


def test_D2_min_font_fail_fixture_gives_one_finding(tmp_path):
    doc, facts = _facts_from_fixture(SEEDED / "geo.min-font" / "fail", tmp_path)
    findings = _check(doc, facts, "geo.min-font")
    assert len(findings) == 1
    assert abs(findings[0].measured["size"] - 12) <= 0.1
    assert findings[0].measured["min"] == 18


def test_D2_min_font_pass_fixture_is_clean(tmp_path):
    doc, facts = _facts_from_fixture(SEEDED / "geo.min-font" / "pass", tmp_path)
    assert _check(doc, facts, "geo.min-font") == []


def test_D3_page_number_in_bottom_margin_is_not_flagged(tmp_path):
    _require_interface()
    root = tmp_path / "render"
    root.mkdir()
    shutil.copytree(lib_dir(), root / "lib")
    main = root / "main.typ"
    main.write_text(
        '#import "/lib/marks.typ": section\n'
        '#set page(paper: "a4", margin: 20mm, footer: context align(center)[#counter(page).display()])\n'
        '#section("s1")[A short paragraph that sits well inside the margins.]\n'
    )
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, root, pdf)
    facts = layout.layout_facts(pdf, main, root)
    assert any(w.section_id is None for w in facts.words), "the page number must lie outside every section"
    doc = Document(front={}, format="doc", sections=[Section(id="s1", intent="body")])
    assert _check(doc, facts, "geo.in-safe-area") == []


def test_D4_rule_metadata():
    _require_interface()
    safe = _rule("geo.in-safe-area")
    font = _rule("geo.min-font")
    for rule in (safe, font):
        assert rule.tier == "geometry"
        assert rule.severity == "error"
        assert rule.status == "active"
    assert safe.remedy.class_ == "restructure"
    assert font.remedy.class_ == "redraft"
