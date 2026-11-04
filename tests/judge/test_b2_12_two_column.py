# Intent: two-column renders comparison sections within its declared capacity.
import re
from pathlib import Path

import yaml

from docla import cli
from docla.model import Document, Item, Section, Source
from docla.render import chooser, components, swatch
from docla.source.serialiser import serialise
from docla.theme import neutral_theme

ROOT = Path(__file__).resolve().parents[2]


def _manifests():
    assert hasattr(components, "all_manifests"), "docla.render.components.all_manifests must exist"
    return components.all_manifests()


def _fixture():
    path = ROOT / "tests/fixtures/components/two-column.yaml"
    assert path.is_file(), "the two-column fixture must exist"
    section = Section.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert section.id and section.intent == "comparison"
    return section


def _render(section, tmp_path):
    _manifests()
    doc = Document(front={"title": "Comparison"}, format="slides", sections=[section])
    return swatch.swatch(doc, section.id, tmp_path, theme=neutral_theme())


def test_D1_manifest_and_original_manifests():
    manifests = _manifests()
    assert "two-column" in manifests
    manifest = manifests["two-column"]
    assert manifest.name == "two-column"
    assert manifest.format == "slides"
    assert list(manifest.intents) == ["comparison"]
    assert {key: tuple(value) for key, value in manifest.capacity.items()} == {
        "title_words": (1, 8),
        "items": (0, 8),
        "paragraphs": (0, 6),
        "item_chars": (10, 100),
    }
    assert list(manifest.elements) == ["title", "item", "paragraph"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_comparison_and_pinned_routes():
    routes = chooser.load_chooser(manifests=_manifests())
    assert routes.knows("comparison", "slides"), "the chooser must have slides entries for intent comparison"
    sections = [
        (Section(id="s1", intent="comparison", title="Options"), "slides", "two-column"),
        (Section(id="s2", intent="comparison", items=[Item(body="A point")]), "slides", "two-column"),
        (Section(id="s3", intent="statement", title="Claim"), "slides", "statement"),
        (Section(id="s4", intent="bullets", items=[Item(body="A point")] * 3), "slides", "bullets"),
        (Section(id="s5", intent="body", paragraphs=["Text"]), "doc", "body"),
        (Section(id="s6", intent="callout", items=[Item(body="A point")]), "doc", "callout"),
    ]
    for section, fmt, expected in sections:
        assert routes.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_marks(tmp_path):
    section = _fixture()
    result = _render(section, tmp_path)
    assert len(result.facts.pages) == 1
    page = result.facts.pages[0]
    assert (page.width, page.height) == (960, 540)
    assert [(mark.id, mark.edge) for mark in result.facts.marks if mark.kind == "section"] == [
        (section.id, "start"),
        (section.id, "end"),
    ]
    roles = {mark.role for mark in result.facts.marks if mark.kind == "element" and mark.id == section.id}
    expected = {"title"} if section.title else set()
    if section.items:
        expected.add("item")
    if section.paragraphs:
        expected.add("paragraph")
    assert expected
    assert expected <= roles


def test_D4_capacity_boundary_fit_marks(tmp_path):
    text = "A clear comparison point " * 4
    assert len(text) == 100
    assert chooser.load_chooser(manifests=_manifests()).knows("comparison", "slides"), "the chooser must have slides entries for intent comparison"

    def fits(count):
        section = Section(
            id="comparison", intent="comparison", title="Compare options", items=[Item(body=text) for _ in range(count)]
        )
        marks = [mark for mark in _render(section, tmp_path).facts.marks if mark.kind == "fit"]
        assert marks, "the component must emit fit marks"
        return [mark.ok for mark in marks]

    assert all(fits(8))
    assert not all(fits(9))


def test_D5_check_fixture_has_no_findings(tmp_path, capsys):
    _manifests()
    section = _fixture()
    keys = {citation.key for item in section.items for citation in item.citations}
    doc = Document(
        front={"doctype": "pitch-deck", "title": "Comparison"},
        format="slides",
        sources=[Source(key=key, text="Reference") for key in sorted(keys)],
        sections=[section],
    )
    path = tmp_path / "deck.md"
    path.write_text(serialise(doc), encoding="utf-8")
    try:
        code = cli.main(["check", str(path), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code or 0
    captured = capsys.readouterr()
    assert code == 0, captured.err + captured.out
    assert captured.out.splitlines() == ["no findings"]


def test_D6_no_colour_literals():
    path = ROOT / "src/docla/render/library/two-column.typ"
    assert path.is_file(), "the two-column Typst component must exist"
    source = path.read_text(encoding="utf-8")
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", source)
