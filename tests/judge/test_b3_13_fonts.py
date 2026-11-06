# Intent: rendered words use only the theme's named font families.
import importlib
import importlib.util
import runpy
import shutil
from pathlib import Path

import pytest

from docla import cli
from docla.checks import catalogue, engine, source
from docla.facts.layout import LayoutFacts, PlacedWord, layout_facts
from docla.facts.models import FactBox, PageFacts
from docla.model import Document, Section
from docla.render import kit, typst
from docla.theme import neutral_theme

try:
    fonts = importlib.import_module("docla.checks.fonts")
except ImportError as error:
    if error.name != "docla.checks.fonts" and not (
        str(error.name).startswith("docla.checks.fonts.") and importlib.util.find_spec("docla.checks.fonts") is None
    ):
        raise
    fonts = None

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects" / "geo.fonts"


def _rule():
    assert fonts is not None and hasattr(fonts, "RULES"), "docla.checks.fonts.RULES must exist"
    rules = [rule for rule in fonts.RULES if rule.id == "geo.fonts"]
    assert len(rules) == 1
    return rules[0]


def _doc():
    return Document(front={}, format="slides", sections=[Section(id="s1", intent="statement")])


def _facts(names):
    words = []
    for index, name in enumerate(names):
        box = FactBox(page=1, x0=100 + index * 100, y0=100, x1=180 + index * 100, y1=120)
        words.append(
            PlacedWord(
                text="Word", font=name, size=24, colour="#1A1A1A", box=box, baseline=118, role=None, section_id="s1"
            )
        )
    page = PageFacts(page=1, width=960, height=540, words=words, shapes=[])
    return LayoutFacts(pdf_sha256="0" * 64, pages=[page], words=words, shapes=[], marks=[])


def test_D1_catalogue_and_rule_metadata():
    rule = _rule()
    assert (rule.title, rule.origin, rule.strength, rule.status) == (
        "Text uses only the theme's type families",
        "manual",
        "hard",
        "active",
    )
    assert (rule.tier, rule.severity, rule.remedy.class_, rule.check) == (
        "geometry",
        "error",
        "engine",
        {"kind": "font-family"},
    )
    assert rule.remedy.hint
    assert rule.provenance.source == {"doc": "DESIGN.md", "section": "10.5"}
    m1 = catalogue.m1_rules()
    assert [r.id for r in m1] == [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
    ]
    assert len(source.RULES) == 2
    all_ids = [r.id for r in catalogue.all_rules()]
    assert all_ids.count("geo.fonts") == 1
    assert all(all_ids.index(r.id) < all_ids.index("geo.fonts") for r in [*m1, *source.M2_RULES])


def test_D2_family_of():
    assert fonts is not None and hasattr(fonts, "family_of"), "docla.checks.fonts.family_of must exist"
    assert [
        fonts.family_of(name)
        for name in ("YTEEEY+Inter-Regular", "XTOYTA+SourceSerif4-Semibold", "XMMEKF+LibertinusSerif-Regular", "Inter")
    ] == ["Inter", "SourceSerif4", "LibertinusSerif", "Inter"]
    assert fonts.family_of("abc+Inter-Regular") == "abc+Inter"


def test_D3_theme_families_and_explicit_allowed():
    rule = _rule()
    names = ["ABCDEF+Inter-SemiBold", "ABCDEF+SourceSerif4-Regular"]
    ctx = engine.CheckContext(doc=_doc(), facts=_facts(names), theme=neutral_theme())
    assert engine.run_checks([rule], ctx) == []
    ctx.facts = _facts([*names, "ABCDEF+Helvetica-Bold", "ABCDEF+Helvetica-Regular"])
    found = engine.run_checks([rule], ctx)
    assert len(found) == 1
    assert found[0].section_id == "s1"
    assert found[0].page == 1
    box = found[0].region
    assert box is not None and (box.x, box.y, box.w, box.h) == (300, 100, 80, 20)
    assert found[0].measured == {"font": "Helvetica", "allowed": ["Inter", "Source Serif 4"]}
    assert "ABCDEF+Helvetica-Bold" in found[0].message
    assert "Inter" in found[0].message and "Source Serif 4" in found[0].message
    restricted = rule.model_copy(update={"check": {"kind": "font-family", "allowed": ["Inter"]}})
    ctx.facts = _facts(names)
    found = engine.run_checks([restricted], ctx)
    assert len(found) == 1 and found[0].measured == {"font": "SourceSerif4", "allowed": ["Inter"]}


@pytest.mark.parametrize("kind,expected", [("fail", "LibertinusSerif"), ("pass", None)])
def test_D4_seeded_defects(tmp_path, kind, expected):
    rule = _rule()
    fixture = FIXTURES / kind / "main.typ"
    assert fixture.is_file(), f"{fixture} must exist"
    shutil.copytree(kit.lib_dir(), tmp_path / "lib")
    main = tmp_path / "main.typ"
    shutil.copy(fixture, main)
    theme = neutral_theme()
    pdf = tmp_path / "out.pdf"
    typst.compile_pdf(main, tmp_path, pdf, [theme.fonts_dir])
    facts = layout_facts(pdf, main, tmp_path, font_paths=[theme.fonts_dir])
    found = engine.run_checks([rule], engine.CheckContext(doc=_doc(), facts=facts, theme=theme))
    if expected is None:
        assert found == []
    else:
        assert len(found) == 1
        assert (found[0].rule_id, found[0].section_id, found[0].severity, found[0].measured["font"]) == (
            "geo.fonts",
            "s1",
            "error",
            expected,
        )


def test_D5_no_theme_or_facts():
    rule = _rule()
    facts = _facts(["ABCDEF+Helvetica-Bold"])
    assert engine.run_checks([rule], engine.CheckContext(doc=_doc(), facts=facts)) == []
    assert engine.run_checks([rule], engine.CheckContext(doc=_doc(), theme=neutral_theme())) == []


def test_D6_clean_working_files(tmp_path, capsys):
    judge_dir = Path(__file__).parent
    examples = [
        runpy.run_path(str(judge_dir / name))
        for name in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py")
    ]
    texts = [
        examples[0]["SLIDES"],
        examples[0]["DOC"],
        examples[1]["SLIDES"],
        examples[1]["DOC"],
        examples[1]["BULLETS_ONLY"],
    ]
    for index, text in enumerate(texts):
        path = tmp_path / f"clean-{index}.md"
        path.write_text(text)
        try:
            code = cli.main(["check", str(path), "--out", str(tmp_path / f"out-{index}")])
        except SystemExit as error:
            code = error.code
        output = capsys.readouterr()
        assert code == 0, (index, output.out, output.err)
        assert output.out.splitlines() == ["no findings"]
