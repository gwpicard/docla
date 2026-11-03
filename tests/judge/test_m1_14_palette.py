# Intent: the geo.palette rule flags text colours far from every theme colour token and passes on-palette text.
import importlib
import shutil
from pathlib import Path

from docla.model import Document, Section

_REPO = Path(__file__).resolve().parents[2]
_FIXTURES = _REPO / "tests" / "fixtures" / "seeded-defects" / "geo.palette"


def _import(module: str):
    try:
        return importlib.import_module(module)
    except ImportError as error:
        name = str(error.name)
        if name not in ("docla", module) and not module.startswith(name + "."):
            raise
        return None


kit = _import("docla.render.kit")
palette = _import("docla.checks.palette")
engine = _import("docla.checks.engine")
compose = _import("docla.render.compose")
layout = _import("docla.facts.layout")
typst = _import("docla.render.typst")

PRELUDE = (
    '#import "/lib/marks.typ": *\n#import "/lib/theme.typ": *\n#set page(width: 960pt, height: 540pt, margin: 0pt)\n'
)


def _need():
    assert kit is not None and hasattr(kit, "read_tokens"), "docla.render.kit.read_tokens must exist"
    assert palette is not None and hasattr(palette, "RULES"), "docla.checks.palette.RULES must exist"
    assert engine is not None and hasattr(engine, "run_checks"), "docla.checks.engine.run_checks must exist"
    assert layout is not None and hasattr(layout, "layout_facts"), "docla.facts.layout.layout_facts must exist"


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(kit.lib_dir(), root / "lib")
    return root


def _rule():
    rules = [r for r in palette.RULES if r.id == "geo.palette"]
    assert len(rules) == 1, "RULES must hold exactly one geo.palette rule"
    return rules[0]


def _doc() -> Document:
    return Document(front={}, format="slides", sections=[Section(id="s1", intent="statement")])


def _findings(root: Path, main: Path, doc: Document, tolerance: float | None = None):
    pdf = root / "out.pdf"
    typst.compile_pdf(main, root, pdf)
    facts = layout.layout_facts(pdf, main, root)
    rule = _rule()
    if tolerance is not None:
        rule = rule.model_copy(update={"check": {**rule.check, "tolerance": tolerance}})
    ctx = engine.CheckContext(doc=doc, facts=facts, tokens=kit.read_tokens(root))
    return [f for f in engine.run_checks([rule], ctx) if f.rule_id == "geo.palette"]


def _inline(root: Path, fill: str) -> Path:
    main = root / "main.typ"
    main.write_text(PRELUDE + f'#section("s1")[#text(fill: rgb("{fill}"))[Hello palette]]\n')
    return main


def _fixture(root: Path, kind: str) -> Path:
    source = _FIXTURES / kind / "main.typ"
    assert source.exists(), f"{source} must exist"
    main = root / "main.typ"
    shutil.copy(source, main)
    return main


def test_D1_read_tokens_returns_normalised_colours_and_leaves_root_clean(tmp_path):
    _need()
    root = _root(tmp_path)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    tokens = kit.read_tokens(root)
    after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    assert tokens == {"ink": "#1A1A1A", "paper": "#FFFFFF", "accent": "#2F5D8A", "muted": "#6B6B6B"}
    assert after == before


def test_D2_fail_fixture_gives_one_off_palette_finding(tmp_path):
    _need()
    root = _root(tmp_path)
    found = _findings(root, _fixture(root, "fail"), _doc())
    assert len(found) == 1
    assert found[0].measured["colour"] == "#FF0000"
    assert found[0].measured["delta_e"] > 2
    assert found[0].section_id == "s1"


def test_D3_pass_fixture_gives_no_finding(tmp_path):
    _need()
    root = _root(tmp_path)
    assert _findings(root, _fixture(root, "pass"), _doc()) == []


def test_D3_composed_statement_and_bullets_give_no_finding(tmp_path):
    _need()
    assert compose is not None and hasattr(compose, "assemble"), "docla.render.compose.assemble must exist"
    doc = Document(
        front={},
        format="slides",
        sections=[
            Section(id="s1", intent="statement", title="One clear claim"),
            Section(id="s2", intent="bullets", title="Points", items=[{"body": "First"}, {"body": "Second"}]),
        ],
    )
    dest = tmp_path / "built"
    main = compose.assemble(compose.compose(doc), dest)
    assert _findings(dest, main, doc) == []


def test_D4_one_step_from_accent_gives_no_finding(tmp_path):
    _need()
    root = _root(tmp_path)
    assert _findings(root, _inline(root, "#2f5d8b"), _doc(), tolerance=2.0) == []


def test_D5_rule_metadata():
    _need()
    rule = _rule()
    assert rule.tier == "geometry"
    assert rule.severity == "error"
    assert rule.remedy.class_ == "engine"
    assert rule.status == "active"
    assert rule.check["kind"] == "colour-in-set"
