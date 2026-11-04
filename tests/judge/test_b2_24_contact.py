# Intent: contact sections route to a capacity-accurate, theme-compatible slide component.
import importlib
import re
from pathlib import Path

import yaml
from docla.model import Document, Item, Section, Source


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not str(error.name).startswith(name + "."):
            raise
        return None


components = _optional("docla.render.components")
chooser_module = _optional("docla.render.chooser")
swatch_module = _optional("docla.render.swatch")
theme_module = _optional("docla.theme")
serialiser = _optional("docla.source.serialiser")
cli = _optional("docla.cli")
ROOT = Path(__file__).resolve().parents[2]


def _manifests():
    assert components is not None and hasattr(components, "all_manifests"), "all_manifests must exist"
    manifests = components.all_manifests()
    assert "contact" in manifests, "contact manifest must exist"
    return manifests


def _fixture():
    _manifests()
    path = ROOT / "tests/fixtures/components/contact.yaml"
    assert path.is_file(), "contact fixture must exist"
    return Section.model_validate(yaml.safe_load(path.read_text()))


def _render(section, tmp_path):
    _manifests()
    assert swatch_module is not None and hasattr(swatch_module, "swatch")
    assert theme_module is not None and hasattr(theme_module, "neutral_theme")
    assert section.id is not None
    doc = Document(front={"doctype": "pitch-deck", "title": "Contacts"}, format="slides", sections=[section])
    return swatch_module.swatch(doc, section.id, tmp_path, theme=theme_module.neutral_theme())


def test_D1_contact_manifest_and_packaged_components():
    manifest = _manifests()["contact"]
    assert manifest.name == "contact"
    assert manifest.format == "slides"
    assert list(manifest.intents) == ["contact"]
    assert {key: tuple(value) for key, value in manifest.capacity.items()} == {
        "title_words": (1, 8), "items": (1, 6), "item_chars": (3, 60)
    }
    assert list(manifest.elements) == ["title", "item"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_contact_and_pinned_routes():
    _manifests()
    assert chooser_module is not None and hasattr(chooser_module, "load_chooser")
    chooser = chooser_module.load_chooser()
    cases = [
        (Section(id="a", intent="contact", title="Contact", items=[Item(body="hello@example.org")]), "slides", "contact"),
        (Section(id="b", intent="statement", title="Claim"), "slides", "statement"),
        (Section(id="c", intent="bullets", items=[Item(body="A point") for _ in range(3)]), "slides", "bullets"),
        (Section(id="d", intent="body", title="Title", paragraphs=["Text"]), "doc", "body"),
        (Section(id="e", intent="callout", title="Title", items=[Item(body="A point")]), "doc", "callout"),
    ]
    for section, fmt, expected in cases:
        assert chooser.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_marks(tmp_path):
    section = _fixture()
    assert section.intent == "contact" and section.title and section.items
    result = _render(section, tmp_path)
    assert len(result.facts.pages) == 1
    page = result.facts.pages[0]
    assert (page.width, page.height) == (960, 540)
    marks = result.facts.marks
    assert {(m.id, m.edge) for m in marks if m.kind == "section"} == {(section.id, "start"), (section.id, "end")}
    assert {m.role for m in marks if m.kind == "element" and m.id == section.id} >= {"title", "item"}


def test_D4_capacity_boundary_fit_marks(tmp_path):
    text = "contact " * 7 + "line"
    assert len(text) == 60
    for count, expected in [(6, True), (7, False)]:
        section = Section(id="contact1", intent="contact", title="Contact us", items=[Item(body=text) for _ in range(count)])
        result = _render(section, tmp_path / str(count))
        fits = [m for m in result.facts.marks if m.kind == "fit"]
        assert fits, "contact must emit fit marks"
        assert all(mark.ok for mark in fits) is expected


def test_D5_fixture_deck_checks_cleanly(tmp_path, capsys):
    section = _fixture()
    assert serialiser is not None and hasattr(serialiser, "serialise")
    assert cli is not None and hasattr(cli, "main")
    keys = sorted({cite.key for item in section.items for cite in item.citations})
    doc = Document(front={"doctype": "pitch-deck", "title": "Contacts"}, format="slides", sections=[section],
                   sources=[Source(key=key, text="Contact source") for key in keys])
    source = tmp_path / "deck.md"
    source.write_text(serialiser.serialise(doc))
    try:
        code = cli.main(["check", str(source), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code if error.code is not None else 0
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert captured.out.splitlines() == ["no findings"]


def test_D6_contact_source_has_no_colour_literals():
    path = ROOT / "src/docla/render/library/contact.typ"
    assert path.is_file(), "contact.typ must exist"
    source = path.read_text()
    assert re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", source) is None
