# Intent: text contrast is checked against rendered backgrounds and citations remain legible on chapter breaks.
import importlib
import importlib.util
import runpy
import shutil
from pathlib import Path

import pytest
import yaml

from docla import cli
from docla.checks import catalogue, engine
from docla.facts.layout import layout_facts
from docla.facts.raster import PdfiumRasteriser
from docla.model import Document, Section
from docla.render import kit, swatch, typst
from docla.source import parser
from docla.source.serialiser import serialise
from docla.theme import neutral_theme

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures"

try:
    pixels = importlib.import_module("docla.checks.pixels")
except ImportError as error:
    if error.name != "docla.checks.pixels" or importlib.util.find_spec("docla.checks.pixels") is not None:
        raise
    pixels = None


def _rule():
    rules = [rule for rule in catalogue.all_rules() if rule.id == "pix.contrast"]
    assert len(rules) == 1, "exactly one pix.contrast rule must exist"
    return rules[0]


def _check(source, out, capsys):
    try:
        code = cli.main(["check", str(source), "--out", str(out)])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out.strip(), captured.err


def test_D1_catalogue_contrast_metadata_and_order():
    rules = catalogue.all_rules()
    ids = [rule.id for rule in rules]
    rule = _rule()
    assert ids.count("pix.blank-page") == 1
    assert ids.index("pix.contrast") == ids.index("pix.blank-page") + 1
    assert (rule.title, rule.origin, rule.tier, rule.severity) == (
        "Text contrasts with its background",
        "manual",
        "pixel",
        "error",
    )
    assert (rule.strength, rule.status) == ("hard", "active")
    assert rule.remedy.class_ == "engine" and rule.remedy.hint.strip()
    assert rule.check == {"kind": "contrast", "min": 4.5}
    assert rule.provenance.source == {"doc": "DESIGN.md", "section": "10.5"}


def test_D2_wcag_ratio_and_symmetry():
    assert pixels is not None and hasattr(pixels, "contrast_ratio"), "pixels.contrast_ratio must exist"
    assert round(pixels.contrast_ratio("#FFFFFF", "#000000"), 2) == 21.0
    assert round(pixels.contrast_ratio("#6B6B6B", "#1A1A1A"), 2) == 3.27
    assert pixels.contrast_ratio("#6B6B6B", "#1A1A1A") == pixels.contrast_ratio("#1A1A1A", "#6B6B6B")


@pytest.mark.parametrize("side", ["fail", "pass"])
def test_D3_seeded_background_and_theme_threshold(tmp_path, side):
    rule = _rule()
    source = FIXTURES / "seeded-defects" / "pix.contrast" / side / "main.typ"
    assert source.is_file(), f"{source} must exist"
    shutil.copytree(kit.lib_dir(), tmp_path / "lib")
    main = tmp_path / "main.typ"
    shutil.copy(source, main)
    theme = neutral_theme()
    fonts = [theme.fonts_dir]
    pdf = tmp_path / "out.pdf"
    typst.compile_pdf(main, tmp_path, pdf, fonts)
    facts = layout_facts(pdf, main, tmp_path, font_paths=fonts)
    pngs = PdfiumRasteriser().render(pdf, tmp_path / "pages")
    doc = Document(front={}, format="slides", sections=[Section(id="s1", intent="statement")])
    found = engine.run_checks([rule], engine.CheckContext(doc, facts, theme=theme, pages_png=pngs))
    if side == "pass":
        assert found == []
    else:
        assert len(found) == 1
        finding = found[0]
        assert (finding.section_id, finding.role, finding.severity, finding.page) == ("s1", "body", "error", 1)
        assert finding.measured == {"ratio": 3.27, "min": 4.5, "text": "#6B6B6B", "background": "#1A1A1A"}
    assert engine.run_checks([rule], engine.CheckContext(doc, facts, theme=theme, pages_png=[])) == []
    if side == "fail":
        colour = theme.tokens.colour.model_copy(update={"contrast_min": 3.0})
        tokens = theme.tokens.model_copy(update={"colour": colour})
        relaxed = theme.model_copy(update={"tokens": tokens})
        assert engine.run_checks([rule], engine.CheckContext(doc, facts, theme=relaxed, pages_png=pngs)) == []


def _cited_source(intent):
    return f'''---
doctype: pitch-deck
format: slides
title: Readout
---

## Sources

- [S1] workshop.vtt, transcript

::: {{#aaaa1 .section intent="{intent}"}}
## The next chapter

- The pipeline drops 12% of readings. [S1 p.4]
:::
'''


@pytest.mark.parametrize(("intent", "colour"), [("chapter-break", "#FFFFFF"), ("bullets", "#6B6B6B")])
def test_D4_citation_words_use_component_colour(tmp_path, intent, colour):
    doc, findings = parser.parse(_cited_source(intent))
    assert findings == []
    result = swatch.swatch(doc, "aaaa1", tmp_path, theme=neutral_theme())
    words = [word for word in result.facts.words if word.text in ("[S1", "p.4]")]
    assert {word.text for word in words} == {"[S1", "p.4]"}
    assert {word.colour for word in words} == {colour}


def test_D4_cited_chapter_break_checks_clean(tmp_path, capsys):
    source = tmp_path / "deck.md"
    source.write_text(_cited_source("chapter-break"), encoding="utf-8")
    code, out, err = _check(source, tmp_path / "out", capsys)
    assert (code, out) == (0, "no findings"), err


@pytest.mark.parametrize("judge", ["test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"])
@pytest.mark.parametrize("name", ["SLIDES", "DOC"])
def test_D5_existing_clean_documents(tmp_path, capsys, judge, name):
    text = runpy.run_path(str(ROOT / "tests/judge" / judge))[name]
    source = tmp_path / "clean.md"
    source.write_text(text, encoding="utf-8")
    code, out, err = _check(source, tmp_path / "out", capsys)
    assert (code, out) == (0, "no findings"), err


@pytest.mark.parametrize("component", ["cards", "key-figures", "quote", "cover", "chapter-break"])
def test_D5_component_fixture_checks_clean(tmp_path, capsys, component):
    section = Section.model_validate(yaml.safe_load((FIXTURES / "components" / f"{component}.yaml").read_text()))
    doc = Document(front={"doctype": "pitch-deck", "title": "Deck"}, format="slides", sections=[section])
    source = tmp_path / "deck.md"
    source.write_text(serialise(doc), encoding="utf-8")
    code, out, err = _check(source, tmp_path / "out", capsys)
    assert (code, out) == (0, "no findings"), err
