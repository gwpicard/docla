# Intent: process sections render as a capacity-true slide component.
import importlib
import re
from pathlib import Path

import yaml


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(str(error.name) + "."):
            raise
        if importlib.util.find_spec(str(error.name)) is not None:
            raise
        return None


components = _optional("docla.render.components")
chooser = _optional("docla.render.chooser")
swatch = _optional("docla.render.swatch")
model = _optional("docla.model")
theme = _optional("docla.theme")
serialiser = _optional("docla.source.serialiser")
cli = _optional("docla.cli")
ROOT = Path(__file__).resolve().parents[2]


def _manifests():
    assert components is not None and hasattr(components, "all_manifests"), "all_manifests must exist"
    return components.all_manifests()


def _fixture():
    manifests = _manifests()
    assert "process" in manifests, "process manifest must exist"
    path = ROOT / "tests/fixtures/components/process.yaml"
    assert path.is_file(), "process fixture must exist"
    assert model is not None and hasattr(model, "Section")
    return model.Section.model_validate(yaml.safe_load(path.read_text()))


def _render(section, tmp_path):
    assert swatch is not None and hasattr(swatch, "swatch")
    assert theme is not None and hasattr(theme, "neutral_theme")
    assert model is not None and hasattr(model, "Document")
    doc = model.Document(front={"title": "Process"}, format="slides", sections=[section])
    return swatch.swatch(doc, section.id, tmp_path, theme=theme.neutral_theme())


def test_D1_process_manifest_and_packaged_components():
    manifests = _manifests()
    assert "process" in manifests
    manifest = manifests["process"]
    assert manifest.name == "process"
    assert manifest.format == "slides"
    assert manifest.intents == ["process"]
    assert manifest.capacity == {"title_words": (1, 8), "items": (3, 6), "item_chars": (10, 60)}
    assert manifest.elements == ["title", "step", "item"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_process_and_pinned_routes():
    manifests = _manifests()
    assert chooser is not None and hasattr(chooser, "load_chooser")
    assert model is not None and hasattr(model, "Section") and hasattr(model, "Item")
    routes = chooser.load_chooser(manifests=manifests)
    assert routes.knows("process", "slides"), "the chooser must have slides entries for intent process"
    sections = [
        ("slides", model.Section(id="p", intent="process"), "process"),
        ("slides", model.Section(id="s", intent="statement", title="Claim"), "statement"),
        ("slides", model.Section(id="b", intent="bullets", items=[model.Item(body="A point")] * 3), "bullets"),
        ("doc", model.Section(id="d", intent="body", paragraphs=["Text"]), "body"),
        ("doc", model.Section(id="c", intent="callout", title="Note"), "callout"),
    ]
    for fmt, section, expected in sections:
        assert routes.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_element_marks(tmp_path):
    section = _fixture()
    assert section.id and section.intent == "process"
    result = _render(section, tmp_path)
    assert [(page.width, page.height) for page in result.facts.pages] == [(960, 540)]
    marks = result.facts.marks
    assert any(m.kind == "section" and m.id == section.id and m.edge == "start" for m in marks)
    roles = {m.role for m in marks if m.kind == "element" and m.id == section.id}
    assert {"title", "step", "item"} <= roles


def test_D4_capacity_boundary_fit_marks(tmp_path):
    section = _fixture()
    assert model is not None and hasattr(model, "Item")
    items = [model.Item(head="Step", body="word " * 11 + "x") for _ in range(7)]
    assert all(len(item.head) + len(item.body) == 60 for item in items)
    for count, expected in [(6, True), (7, False)]:
        candidate = section.model_copy(update={"items": items[:count]})
        result = _render(candidate, tmp_path / str(count))
        fits = [m.ok for m in result.facts.marks if m.kind == "fit"]
        assert fits
        assert all(fits) is expected


def test_D5_fixture_deck_check_is_clean(tmp_path, capsys):
    section = _fixture()
    assert serialiser is not None and hasattr(serialiser, "serialise")
    assert cli is not None and hasattr(cli, "main")
    doc = model.Document(front={"doctype": "pitch-deck", "title": "Process"}, format="slides", sections=[section])
    source = tmp_path / "deck.md"
    source.write_text(serialiser.serialise(doc))
    try:
        code = cli.main(["check", str(source), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr().out
    assert code == 0, output
    assert "no findings" in output.splitlines()


def test_D6_process_source_has_no_colour_literals():
    path = ROOT / "src/docla/render/library/process.typ"
    assert path.is_file(), "process.typ must exist"
    source = path.read_text()
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", source)
