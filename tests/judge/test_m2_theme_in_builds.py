# Intent: build, check and swatch use a theme, and the geometry rules take their limits from its tokens.
import json
import shutil
from pathlib import Path

import pdfplumber
import yaml
from pydantic import TypeAdapter

import docla
from docla.facts.layout import LayoutFacts, PlacedWord
from docla.facts.models import FactBox, PageFacts
from docla.model import Document, Finding, Item, Section

try:
    from docla import cli
except ImportError as error:
    if error.name != "docla" and not str(error.name).startswith("docla."):
        raise
    cli = None

try:
    import docla.theme as theme_module
except ImportError as error:
    if error.name != "docla.theme" and not str(error.name).startswith("docla.theme."):
        raise
    theme_module = None

try:
    from docla.checks import engine
except ImportError as error:
    if error.name not in ("docla.checks", "docla.checks.engine"):
        raise
    engine = None

try:
    from docla.checks import catalogue
except ImportError as error:
    if error.name not in ("docla.checks", "docla.checks.catalogue"):
        raise
    catalogue = None

try:
    from docla.render import swatch as swatch_module
except ImportError as error:
    if error.name not in ("docla.render", "docla.render.swatch"):
        raise
    swatch_module = None

SEEDED = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects"
NEUTRAL_DIR = Path(docla.__file__).resolve().parent / "themes" / "neutral"
THEME_FONTS = ("Inter", "SourceSerif4")

SLIDES = """---
doctype: pitch-deck
format: slides
title: Readout
---

## Sources

- [S1] workshop.vtt, transcript

::: {#aaaa1 .section intent="statement"}
## One pilot is enough
:::

::: {#aaaa2 .section intent="bullets"}
## Why it works

- Short intervals catch drift early. [S1 00:41]
- Cheap to repeat. [S1 00:41]
- Easy to explain. [S1 00:41]
:::
"""

BULLETS_ONLY = SLIDES.split("::: {#aaaa1")[0] + "::: {#aaaa2" + SLIDES.split("::: {#aaaa2")[1]

DOC = """---
doctype: report
format: doc
title: Note
---

## Sources

- [S1] workshop.vtt, transcript

::: {#bbbb1 .section intent="body"}
## Findings

The pipeline drops some readings, and the team agreed to measure how many. [S1 00:41]
:::

::: {#bbbb2 .section intent="callout"}
## Note

Measure the dropped readings first. [S1 00:41]
:::
"""


def _run(argv, capsys):
    """Run cli.main(argv); return (exit code, stdout, stderr)."""
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    try:
        code = cli.main(argv)
    except SystemExit as exit_:
        code = exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _need_theme():
    assert theme_module is not None, "docla.theme must exist"
    assert hasattr(theme_module, "neutral_theme"), "docla.theme.neutral_theme must exist"
    return theme_module.neutral_theme()


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def _font_names(pdf: Path) -> set[str]:
    with pdfplumber.open(pdf) as opened:
        return {char["fontname"] for page in opened.pages for char in page.chars}


def _theme_copy(tmp_path: Path, edit) -> Path:
    _need_theme()
    tokens = NEUTRAL_DIR / "tokens.yaml"
    assert tokens.is_file(), "the neutral theme must have a tokens.yaml"
    copy = tmp_path / "theme-copy"
    shutil.copytree(NEUTRAL_DIR, copy)
    data = yaml.safe_load(tokens.read_text())
    edit(data)
    (copy / "tokens.yaml").write_text(yaml.safe_dump(data))
    return copy


def test_D1_build_slides_without_theme_uses_neutral_fonts(tmp_path, capsys):
    _need_theme()
    source = _write(tmp_path, "deck.md", SLIDES)
    out_dir = tmp_path / "out"
    code, _, err = _run(["build", str(source), "--out", str(out_dir)], capsys)
    assert code == 0, err
    names = _font_names(out_dir / "deck.pdf")
    assert names, "the PDF has no text"
    assert all(any(font in name for font in THEME_FONTS) for name in names), names
    assert any("Inter" in name for name in names), names


def test_D1_build_with_theme_folder_matches_default(tmp_path, capsys):
    _need_theme()
    source = _write(tmp_path, "deck.md", SLIDES)
    out_dir = tmp_path / "out"
    code, _, err = _run(["build", str(source), "--out", str(out_dir), "--theme", str(NEUTRAL_DIR)], capsys)
    assert code == 0, err
    names = _font_names(out_dir / "deck.pdf")
    assert names and all(any(font in name for font in THEME_FONTS) for name in names), names


def test_D2_check_clean_slides_and_doc_without_theme_report_no_findings(tmp_path, capsys):
    _need_theme()
    for name, text in (("deck.md", SLIDES), ("note.md", DOC)):
        source = _write(tmp_path, name, text)
        code, out, _ = _run(["check", str(source), "--out", str(tmp_path / ("out-" + name))], capsys)
        assert code == 0, (name, out)
        assert out.splitlines() == ["no findings"], (name, out)


def test_D2_check_pass_fixtures_give_no_text_fits_or_safe_area_finding(tmp_path, capsys):
    _need_theme()
    for rule_id in ("geo.text-fits", "geo.in-safe-area"):
        fixture = SEEDED / rule_id / "pass" / "doc.md"
        out_dir = tmp_path / ("out-" + rule_id)
        code, out, _ = _run(["check", str(fixture), "--out", str(out_dir)], capsys)
        assert (out_dir / "doc.findings.json").is_file(), out
        report = json.loads((out_dir / "doc.findings.json").read_text())
        assert [f for f in report if f["rule_id"] in ("geo.text-fits", "geo.in-safe-area")] == [], (rule_id, out)
        assert code == 0, (rule_id, out)


def test_D3_wide_theme_margins_report_safe_area_but_neutral_does_not(tmp_path, capsys):
    _need_theme()
    source = _write(tmp_path, "deck.md", BULLETS_ONLY)

    def widen(data):
        data["pages"]["slides"]["margin"] = {side: "120pt" for side in ("top", "right", "bottom", "left")}

    copy = _theme_copy(tmp_path, widen)
    out_neutral = tmp_path / "out-neutral"
    _run(["check", str(source), "--out", str(out_neutral)], capsys)
    assert (out_neutral / "deck.findings.json").is_file(), "check must write the findings file"
    neutral = TypeAdapter(list[Finding]).validate_python(json.loads((out_neutral / "deck.findings.json").read_text()))
    assert [f for f in neutral if f.rule_id == "geo.in-safe-area"] == []

    out_copy = tmp_path / "out-copy"
    code, out, _ = _run(["check", str(source), "--out", str(out_copy), "--theme", str(copy)], capsys)
    assert (out_copy / "deck.findings.json").is_file(), out
    wide = TypeAdapter(list[Finding]).validate_python(json.loads((out_copy / "deck.findings.json").read_text()))
    hits = [f for f in wide if f.rule_id == "geo.in-safe-area"]
    assert [f.section_id for f in hits] == ["aaaa2"], out
    assert code == 1


def test_D4_theme_min_size_sets_min_font_threshold(tmp_path, capsys):
    _need_theme()
    source = _write(tmp_path, "deck.md", BULLETS_ONLY)

    def raise_minimum(data):
        data["type"]["scale"]["slides"]["min_size"] = 24

    copy = _theme_copy(tmp_path, raise_minimum)
    out_copy = tmp_path / "out-copy"
    code, out, _ = _run(["check", str(source), "--out", str(out_copy), "--theme", str(copy)], capsys)
    assert (out_copy / "deck.findings.json").is_file(), out
    findings = TypeAdapter(list[Finding]).validate_python(json.loads((out_copy / "deck.findings.json").read_text()))
    hits = [f for f in findings if f.rule_id == "geo.min-font"]
    assert len(hits) >= 1, out
    assert all(f.measured["min"] == 24 for f in hits)
    assert code == 1


def _facts_with_word(colour: str) -> LayoutFacts:
    box = FactBox(page=1, x0=100, y0=100, x1=200, y1=120)
    word = PlacedWord(
        text="Chart", font="Inter-Regular", size=24, colour=colour, box=box, baseline=118, role=None, section_id="s1"
    )
    page = PageFacts(page=1, width=960, height=540, words=[word], shapes=[])
    return LayoutFacts(pdf_sha256="0" * 64, pages=[page], words=[word], shapes=[], marks=[])


def _palette_findings(colour: str):
    theme = _need_theme()
    assert engine is not None and hasattr(engine, "CheckContext") and hasattr(engine, "run_checks")
    assert catalogue is not None and hasattr(catalogue, "m1_rules"), "docla.checks.catalogue.m1_rules must exist"
    import dataclasses

    assert "theme" in {f.name for f in dataclasses.fields(engine.CheckContext)}, "CheckContext must accept a theme"
    doc = Document(front={}, format="slides", sections=[Section(id="s1", intent="statement")])
    ctx = engine.CheckContext(doc=doc, facts=_facts_with_word(colour), theme=theme)
    rules = [r for r in catalogue.m1_rules() if r.id == "geo.palette"]
    return engine.run_checks(rules, ctx)


def test_D5_chart_colour_gives_no_palette_finding():
    assert [f for f in _palette_findings("#00A37A") if f.rule_id == "geo.palette"] == []


def test_D5_off_theme_colour_gives_one_palette_finding():
    hits = [f for f in _palette_findings("#FF0000") if f.rule_id == "geo.palette"]
    assert len(hits) == 1
    assert hits[0].section_id == "s1"
    assert hits[0].measured["colour"] == "#FF0000"


def test_D6_theme_folder_without_tokens_exits_2_naming_tokens_yaml(tmp_path, capsys):
    _need_theme()
    source = _write(tmp_path, "deck.md", SLIDES)
    empty = tmp_path / "empty-theme"
    empty.mkdir()
    code, _, err = _run(["check", str(source), "--out", str(tmp_path / "out"), "--theme", str(empty)], capsys)
    assert code == 2
    assert "tokens.yaml" in err


def test_D6_swatch_with_neutral_theme_uses_theme_fonts(tmp_path):
    theme = _need_theme()
    assert swatch_module is not None and hasattr(swatch_module, "swatch"), "docla.render.swatch.swatch must exist"
    doc = Document(
        front={"title": "Deck"},
        format="slides",
        sections=[
            Section(
                id="s2",
                intent="bullets",
                title="Quokka midsection",
                items=[Item(head="Marmot", body="First point about burrows")],
            )
        ],
    )
    render = swatch_module.swatch(doc, "s2", tmp_path, theme=theme)
    fonts = {word.font for word in render.facts.words}
    assert fonts, "the swatch has no text"
    assert all(any(name in font for name in THEME_FONTS) for font in fonts), fonts
