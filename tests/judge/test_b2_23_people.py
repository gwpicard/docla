# Intent: the people component routes and renders a capacity-true slide using the neutral theme.
import importlib
import importlib.util
import re
from pathlib import Path

import yaml


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name or ""
        if (missing == name or missing.startswith(name + ".")) and importlib.util.find_spec(name) is None:
            return None
        raise


components = _optional("docla.render.components")
chooser_module = _optional("docla.render.chooser")
swatch_module = _optional("docla.render.swatch")
model = _optional("docla.model")
theme = _optional("docla.theme")
source = _optional("docla.source")
cli = _optional("docla.cli")
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/people.yaml"


def _need(module, name):
    assert module is not None and hasattr(module, name), f"{name} must exist"
    return getattr(module, name)


def _manifests():
    return _need(components, "all_manifests")()


def _fixture():
    assert FIXTURE.is_file(), "people fixture must exist"
    return _need(model, "Section").model_validate(yaml.safe_load(FIXTURE.read_text()))


def _document(section):
    return _need(model, "Document")(
        front={"doctype": "pitch-deck", "format": "slides", "title": "Team"},
        format="slides", sections=[section],
    )


def _render(section, tmp_path):
    assert "people" in _manifests(), "people manifest must exist"
    return _need(swatch_module, "swatch")(_document(section), section.id, tmp_path, theme=_need(theme, "neutral_theme")())


def test_D1_people_manifest_and_packaged_components():
    manifests = _manifests()
    assert "people" in manifests
    manifest = manifests["people"]
    assert (manifest.name, manifest.format, list(manifest.intents)) == ("people", "slides", ["people"])
    assert {key: tuple(value) for key, value in manifest.capacity.items()} == {
        "title_words": (1, 8), "items": (2, 6), "item_chars": (3, 50)
    }
    assert list(manifest.elements) == ["title", "name", "role"]
    assert manifest.label.strip()
    assert sorted(_need(components, "load_manifests")()) == ["body", "bullets", "callout", "statement"]


def test_D2_people_and_pinned_routes():
    chooser = _need(chooser_module, "load_chooser")(manifests=_manifests())
    assert chooser.knows("people", "slides"), "the chooser must have slides entries for intent people"
    Section = _need(model, "Section")
    Item = _need(model, "Item")
    cases = [
        ("slides", Section(id="a", intent="people", title="Team", items=[Item(head="Ada", body="Lead"), Item(head="Jo", body="Designer")]), "people"),
        ("slides", Section(id="b", intent="statement", title="Claim"), "statement"),
        ("slides", Section(id="c", intent="bullets", items=[Item(body="A point") for _ in range(3)]), "bullets"),
        ("doc", Section(id="d", intent="body", title="Text", paragraphs=["Text"]), "body"),
        ("doc", Section(id="e", intent="callout", items=[Item(body="A point")]), "callout"),
    ]
    for fmt, section, expected in cases:
        assert chooser.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_renders_page_and_marks(tmp_path):
    section = _fixture()
    result = _render(section, tmp_path)
    assert len(result.facts.pages) == 1
    page = result.facts.pages[0]
    assert (page.width, page.height) == (960, 540)
    assert any(m.kind == "section" and m.id == section.id and m.edge == "start" for m in result.facts.marks)
    roles = {m.role for m in result.facts.marks if m.kind == "element" and m.id == section.id}
    assert {"title", "name", "role"} <= roles


def test_D4_capacity_boundary_fit_marks(tmp_path):
    Section = _need(model, "Section")
    Item = _need(model, "Item")

    def render(count, folder):
        folder.mkdir()
        section = Section(id="team1", intent="people", title="Our team", items=[
            Item(head="Alex Morgan", body="Senior specialist in public service del") for _ in range(count)
        ])
        assert all(len(item.head) + len(item.body) == 50 for item in section.items)
        result = _render(section, folder)
        return [mark for mark in result.facts.marks if mark.kind == "fit"]

    fits = render(6, tmp_path / "six")
    assert fits and all(mark.ok for mark in fits)
    overflow = render(7, tmp_path / "seven")
    assert overflow and any(not mark.ok for mark in overflow)


def test_D5_fixture_deck_check_is_clean(tmp_path, capsys):
    section = _fixture()
    assert section.intent == "people"
    assert "people" in _manifests()
    path = tmp_path / "deck.md"
    path.write_text(_need(source, "serialise")(_document(section)))
    try:
        code = _need(cli, "main")(["check", str(path), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr()
    assert code == 0, (output.out, output.err)
    assert "no findings" in output.out.splitlines()


def test_D6_people_typ_has_no_colour_literals():
    path = ROOT / "src/docla/render/library/people.typ"
    assert path.is_file(), "people.typ must exist"
    text = path.read_text()
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", text)
