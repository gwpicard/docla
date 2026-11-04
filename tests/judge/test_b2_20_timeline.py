# Intent: chronology sections render as capacity-accurate timeline slides.
import importlib
import importlib.util
import re
from pathlib import Path

import pytest
import yaml


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = str(error.name)
        if missing != name and not name.startswith(missing + "."):
            raise
        if importlib.util.find_spec(missing) is not None:
            raise
        return None


components = _optional("docla.render.components")
chooser_module = _optional("docla.render.chooser")
compose_module = _optional("docla.render.compose")
swatch_module = _optional("docla.render.swatch")
marks = _optional("docla.render.marks")
theme = _optional("docla.theme")
model = _optional("docla.model")
source = _optional("docla.source")
cli = _optional("docla.cli")
doctypes = _optional("docla.doctypes")


def _require(module, *names):
    assert module is not None, "public module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"
    return module


def _timeline():
    api = _require(components, "all_manifests")
    manifests = api.all_manifests()
    assert "timeline" in manifests, "timeline manifest must exist"
    return manifests["timeline"]


def _fixture():
    _timeline()
    path = Path(__file__).resolve().parents[1] / "fixtures/components/timeline.yaml"
    assert path.is_file(), "timeline fixture must exist"
    return _require(model, "Section").Section.model_validate(yaml.safe_load(path.read_text()))


def _render(section, tmp_path):
    _timeline()
    _require(model, "Document")
    _require(theme, "neutral_theme")
    _require(swatch_module, "swatch")
    doc = model.Document(front={}, format="slides", sections=[section])
    return swatch_module.swatch(doc, section.id, tmp_path, theme=theme.neutral_theme())


def test_D1_manifest_and_packaged_components():
    manifest = _timeline()
    assert manifest.name == "timeline"
    assert manifest.format == "slides"
    assert list(manifest.intents) == ["chronology"]
    assert {key: tuple(value) for key, value in manifest.capacity.items()} == {
        "title_words": (1, 8),
        "items": (2, 6),
        "item_chars": (10, 70),
    }
    assert list(manifest.elements) == ["title", "item", "date"]
    assert manifest.label.strip()
    assert set(_require(components, "load_manifests").load_manifests()) == {"statement", "bullets", "body", "callout"}


def test_D2_chooser_routes_chronology_and_preserves_existing_routes():
    _timeline()
    _require(chooser_module, "load_chooser")
    _require(model, "Section", "Item")
    chooser = chooser_module.load_chooser()
    for fmt, intent, count, expected in [
        ("slides", "chronology", 2, "timeline"),
        ("slides", "statement", 0, "statement"),
        ("slides", "bullets", 3, "bullets"),
        ("doc", "body", 0, "body"),
        ("doc", "callout", 1, "callout"),
    ]:
        section = model.Section(
            id="s", intent=intent, title="Title", items=[model.Item(body="A short event") for _ in range(count)]
        )
        assert chooser.choose(section, fmt, 0, 1) == expected
    _require(compose_module, "component_for")
    assert compose_module.component_for(model.Section(id="s", intent="timeline"), "slides") is None


def test_D3_fixture_page_and_marks(tmp_path):
    section = _fixture()
    result = _render(section, tmp_path)
    _require(marks, "SectionMark", "ElementMark")
    assert len(result.facts.pages) == 1
    page = result.facts.pages[0]
    assert (page.width, page.height) == (960, 540)
    section_marks = [m for m in result.facts.marks if isinstance(m, marks.SectionMark)]
    assert [(m.id, m.edge) for m in section_marks] == [(section.id, "start"), (section.id, "end")]
    elements = [m for m in result.facts.marks if isinstance(m, marks.ElementMark)]
    assert {m.role for m in elements} >= {"title", "item", "date"}
    assert all(m.id == section.id for m in elements)
    dates = [m for m in elements if m.role == "date"]
    assert len(dates) == len(section.items)
    assert [m.x for m in dates] == sorted(m.x for m in dates)


def test_D4_capacity_boundary_reports_overflow(tmp_path):
    _require(model, "Section", "Item")
    _require(marks, "FitMark")
    for count, expected in [(6, True), (7, False)]:
        section = model.Section(
            id="timeline",
            intent="chronology",
            title="Timeline",
            items=[model.Item(head=str(2000 + i), body="event " * 10 + "event here") for i in range(count)],
        )
        assert all(len(item.body) == 70 for item in section.items)
        result = _render(section, tmp_path)
        fits = [m for m in result.facts.marks if isinstance(m, marks.FitMark)]
        assert fits
        assert all(m.ok for m in fits) is expected


def test_D5_check_fixture_deck(tmp_path, capsys):
    section = _fixture()
    _require(model, "Document")
    _require(source, "serialise")
    _require(cli, "main")
    doc = model.Document(
        front={"doctype": "pitch-deck", "format": "slides", "title": "Timeline"}, format="slides", sections=[section]
    )
    path = tmp_path / "deck.md"
    path.write_text(source.serialise(doc))
    code = cli.main(["check", str(path), "--out", str(tmp_path / "out")])
    output = capsys.readouterr()
    assert code == 0, output.err
    assert output.out.splitlines() == ["no findings"]


def test_D6_no_colour_literals():
    _timeline()
    path = Path(__file__).resolve().parents[2] / "src/docla/render/library/timeline.typ"
    assert path.is_file(), "timeline.typ must exist"
    text = path.read_text()
    assert all(literal not in text for literal in ("rgb(", "luma(", "cmyk("))
    assert re.search(r"#[0-9a-fA-F]{6}", text) is None


def test_D7_timeline_intent_remains_unknown(tmp_path):
    _require(model, "Section")
    _require(compose_module, "component_for")
    _require(doctypes, "load_doctype", "DoctypeError")
    assert compose_module.component_for(model.Section(id="s", intent="timeline"), "slides") is None
    path = tmp_path / "tl.yaml"
    path.write_text(
        "name: tl\nformat: slides\naudience: Readers\nlength: {slides: [1, 5]}\n"
        "questions: []\noutline:\n  - section: events\n    intent: timeline\nchecks: []\nchecklist: []\n"
    )
    with pytest.raises(doctypes.DoctypeError, match="timeline"):
        doctypes.load_doctype(path)
