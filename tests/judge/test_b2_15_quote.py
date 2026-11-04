# Intent: quote sections route to a theme-driven slide component with truthful capacity.
import re
from pathlib import Path

import yaml

from docla import cli
from docla.model import Document, Item, Section
from docla.render import chooser, components, swatch
from docla.source import serialiser
from docla.theme import neutral_theme

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/quote.yaml"


def _manifests():
    assert hasattr(components, "all_manifests"), "docla.render.components.all_manifests must exist"
    return components.all_manifests()


def _fixture():
    assert FIXTURE.is_file(), "quote component fixture must exist"
    section = Section.model_validate(yaml.safe_load(FIXTURE.read_text(encoding="utf-8")))
    assert section.intent == "quote"
    assert len(section.paragraphs) == 1 and section.paragraphs[0].strip()
    assert section.source_line and section.source_line.strip()
    return section


def _render(section, tmp_path):
    _manifests()
    doc = Document(front={"title": "Quote"}, format="slides", sections=[section])
    return swatch.swatch(doc, section.id, tmp_path, theme=neutral_theme())


def test_D1_quote_manifest_and_packaged_components():
    manifests = _manifests()
    assert "quote" in manifests
    manifest = manifests["quote"]
    assert manifest.name == "quote"
    assert manifest.format == "slides"
    assert list(manifest.intents) == ["quote"]
    assert {key: tuple(value) for key, value in manifest.capacity.items()} == {
        "title_words": (0, 8),
        "paragraphs": (1, 1),
    }
    assert list(manifest.elements) == ["quote", "source"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_quote_and_pinned_routes():
    routes = chooser.load_chooser(manifests=_manifests())
    cases = [
        (Section(id="q", intent="quote", paragraphs=["A quotation"], source_line="A speaker"), "slides", "quote"),
        (Section(id="s", intent="statement", title="A claim"), "slides", "statement"),
        (Section(id="b", intent="bullets", title="Points", items=[Item(body="A point")] * 3), "slides", "bullets"),
        (Section(id="d", intent="body", title="Body", paragraphs=["Text"]), "doc", "body"),
        (Section(id="c", intent="callout", title="Callout", items=[Item(body="A point")]), "doc", "callout"),
    ]
    for section, fmt, expected in cases:
        assert routes.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_renders_one_slide_with_marks(tmp_path):
    section = _fixture()
    result = _render(section, tmp_path)
    assert [(page.width, page.height) for page in result.facts.pages] == [(960, 540)]
    assert {(m.id, m.edge) for m in result.facts.marks if m.kind == "section"} == {
        (section.id, "start"),
        (section.id, "end"),
    }
    roles = {m.role for m in result.facts.marks if m.kind == "element" and m.id == section.id}
    assert {"quote", "source"} <= roles


def test_D4_quote_capacity_boundary(tmp_path):
    section = _fixture()
    quote = "word " * 40
    assert len(quote) == 200
    for text, expected in ((quote, True), (quote + "x", False)):
        result = _render(section.model_copy(update={"paragraphs": [text]}), tmp_path)
        fits = [mark.ok for mark in result.facts.marks if mark.kind == "fit"]
        assert fits, "the quote slide must emit fit marks"
        assert all(fits) is expected


def test_D5_fixture_working_file_checks_cleanly(tmp_path, capsys):
    section = _fixture()
    _manifests()
    doc = Document(front={"doctype": "pitch-deck", "title": "Quote"}, format="slides", sections=[section])
    working = tmp_path / "deck.md"
    working.write_text(serialiser.serialise(doc), encoding="utf-8")
    try:
        code = cli.main(["check", str(working), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    assert code == 0, (captured.out, captured.err)
    assert "no findings" in captured.out.splitlines()


def test_D6_quote_typ_contains_no_colour_literals():
    path = ROOT / "src/docla/render/library/quote.typ"
    assert path.is_file(), "quote.typ must exist"
    source = path.read_text(encoding="utf-8")
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", source)
