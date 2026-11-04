# Intent: agenda sections route to a numbered slide component with a truthful capacity.
import re
from pathlib import Path

import yaml

from docla import cli
from docla.model import Document, Item, Section, Source
from docla.render import chooser, components, marks, swatch
from docla.source.serialiser import serialise
from docla.theme import neutral_theme

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/agenda.yaml"


def _manifests():
    assert hasattr(components, "all_manifests"), "docla.render.components.all_manifests must exist"
    return components.all_manifests()


def _fixture():
    assert FIXTURE.is_file(), "the agenda section fixture must exist"
    return Section.model_validate(yaml.safe_load(FIXTURE.read_text()))


def _render(section, tmp_path):
    assert "agenda" in _manifests(), "the agenda manifest must exist"
    doc = Document(front={"title": "Agenda"}, format="slides", sections=[section])
    return swatch.swatch(doc, section.id, tmp_path, theme=neutral_theme()).facts


def test_D1_agenda_manifest_and_packaged_components():
    manifests = _manifests()
    assert "agenda" in manifests
    manifest = manifests["agenda"]
    assert manifest.name == "agenda"
    assert manifest.format == "slides"
    assert manifest.intents == ["agenda"]
    assert manifest.capacity == {"title_words": (1, 8), "items": (2, 8), "item_chars": (3, 60)}
    assert manifest.elements == ["title", "item", "number"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_packaged_chooser_routes_agenda_and_pinned_intents():
    routing = chooser.load_chooser(manifests=_manifests())
    assert routing.knows("agenda", "slides"), "the chooser must have slides entries for intent agenda"
    cases = [
        ("slides", Section(id="a", intent="agenda", title="Agenda", items=[Item(body="First"), Item(body="Second")]), "agenda"),
        ("slides", Section(id="b", intent="statement", title="Claim"), "statement"),
        ("slides", Section(id="c", intent="bullets", items=[Item(body="A point") for _ in range(3)]), "bullets"),
        ("doc", Section(id="d", intent="body", title="Title", paragraphs=["Text"]), "body"),
        ("doc", Section(id="e", intent="callout", title="Title", items=[Item(body="A point")]), "callout"),
    ]
    for fmt, section, expected in cases:
        assert routing.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_renders_one_page_with_marks(tmp_path):
    section = _fixture()
    assert section.id and section.intent == "agenda" and section.title and section.items
    facts = _render(section, tmp_path)
    assert len(facts.pages) == 1
    assert (facts.pages[0].width, facts.pages[0].height) == (960, 540)
    assert {(m.edge, m.id) for m in facts.marks if isinstance(m, marks.SectionMark)} == {
        ("start", section.id), ("end", section.id)
    }
    roles = [m.role for m in facts.marks if isinstance(m, marks.ElementMark) and m.id == section.id]
    assert "title" in roles
    assert roles.count("item") >= len(section.items)
    assert roles.count("number") >= len(section.items)


def test_D4_capacity_boundary_fit_marks(tmp_path):
    def fits(count):
        section = Section(id="agenda1", intent="agenda", title="Agenda", items=[Item(body="word " * 12) for _ in range(count)])
        facts = _render(section, tmp_path / str(count))
        return [m for m in facts.marks if isinstance(m, marks.FitMark)]

    maximum = fits(8)
    assert maximum and all(mark.ok for mark in maximum)
    overflow = fits(9)
    assert overflow and any(not mark.ok for mark in overflow)


def test_D5_fixture_working_file_checks_cleanly(tmp_path, capsys):
    section = _fixture()
    keys = {citation.key for item in section.items for citation in item.citations}
    doc = Document(front={"doctype": "pitch-deck", "title": "Agenda"}, format="slides", sections=[section],
                   sources=[Source(key=key, text="Workshop transcript") for key in sorted(keys)])
    source = tmp_path / "agenda.md"
    source.write_text(serialise(doc))
    _manifests()
    try:
        code = cli.main(["check", str(source), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr()
    assert code == 0, (output.out, output.err)
    assert output.out.splitlines() == ["no findings"]


def test_D6_agenda_source_has_no_colour_literals():
    path = ROOT / "src/docla/render/library/agenda.typ"
    assert path.is_file(), "agenda.typ must exist"
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", path.read_text())
