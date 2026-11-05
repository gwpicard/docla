# Intent: matrix sections render as marked slides within their advertised capacity.
import importlib
import importlib.util
import re
from pathlib import Path

import yaml


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not str(error.name).startswith(name + "."):
            raise
        if importlib.util.find_spec(str(error.name)) is not None:
            raise
        return None


cli = _optional("docla.cli")
model = _optional("docla.model")
chooser = _optional("docla.render.chooser")
components = _optional("docla.render.components")
swatch = _optional("docla.render.swatch")
serialiser = _optional("docla.source.serialiser")
theme = _optional("docla.theme")
golden = _optional("docla.testing.golden")

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/matrix.yaml"


def _manifests():
    assert components is not None and hasattr(components, "all_manifests"), "all_manifests must exist"
    manifests = components.all_manifests()
    assert "matrix" in manifests, "matrix manifest must exist"
    return manifests


def _fixture():
    assert _manifests()["matrix"].fixture == "tests/fixtures/components/matrix.yaml"
    assert FIXTURE.is_file(), "matrix fixture must exist"
    assert model is not None and hasattr(model, "Section")
    section = model.Section.model_validate(yaml.safe_load(FIXTURE.read_text(encoding="utf-8")))
    assert section.id and section.intent == "matrix"
    return section


def _document(section):
    assert model is not None and hasattr(model, "Document")
    return model.Document(front={"doctype": "pitch-deck", "title": "Matrix"}, format="slides", sections=[section])


def _render(section, tmp_path):
    _manifests()
    assert swatch is not None and hasattr(swatch, "swatch")
    assert theme is not None and hasattr(theme, "neutral_theme")
    return swatch.swatch(_document(section), section.id, tmp_path, theme=theme.neutral_theme())


def test_D1_matrix_manifest_and_packaged_components():
    manifest = _manifests()["matrix"]
    assert manifest.name == "matrix"
    assert manifest.format == "slides"
    assert list(manifest.intents) == ["matrix"]
    assert {key: tuple(value) for key, value in manifest.capacity.items()} == {
        "title_words": (1, 8), "items": (4, 4), "item_chars": (10, 70)
    }
    assert list(manifest.elements) == ["title", "quadrant", "axis-label"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_matrix_and_pinned_routes():
    assert chooser is not None and hasattr(chooser, "load_chooser")
    assert model is not None and hasattr(model, "Section") and hasattr(model, "Item")
    routing = chooser.load_chooser(manifests=_manifests())
    cases = [
        (model.Section(id="m", intent="matrix", items=[model.Item(body="A quadrant") for _ in range(4)]), "slides", "matrix"),
        (model.Section(id="s", intent="statement", title="Claim"), "slides", "statement"),
        (model.Section(id="b", intent="bullets", items=[model.Item(body="A point") for _ in range(3)]), "slides", "bullets"),
        (model.Section(id="d", intent="body", paragraphs=["A paragraph"]), "doc", "body"),
        (model.Section(id="c", intent="callout", items=[model.Item(body="A callout")]), "doc", "callout"),
    ]
    for section, fmt, expected in cases:
        assert routing.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_renders_marked_slide(tmp_path):
    section = _fixture()
    assert section.data and section.data.get("x") and section.data.get("y")
    result = _render(section, tmp_path)
    assert len(result.facts.pages) == 1
    assert (result.facts.pages[0].width, result.facts.pages[0].height) == (960, 540)
    marks = result.facts.marks
    assert {(m.id, m.edge) for m in marks if m.kind == "section"} == {
        (section.id, "start"), (section.id, "end")
    }
    elements = [m for m in marks if m.kind == "element" and m.id == section.id]
    assert {m.role for m in elements} >= {"title", "quadrant", "axis-label"}
    assert sum(m.role == "quadrant" for m in elements) == 4
    assert golden is not None and hasattr(golden, "facts_for")
    assert {"title", "quadrant", "axis-label"} <= golden.facts_for("matrix", FIXTURE.parent).keys()


def test_D4_capacity_boundary_is_reflected_in_fit_marks(tmp_path):
    section = _fixture()
    assert model is not None and hasattr(model, "Item")
    head, body = "head " * 4, "body " * 10
    assert len(head) == 20 and len(body) == 50
    cases = [
        ([model.Item(head=head, body=body) for _ in range(4)], True),
        ([model.Item(head=head, body=body + "x")] + [model.Item(head=head, body=body) for _ in range(3)], False),
        ([model.Item(head="head " * 14 + "x", body="")] + [model.Item(head=head, body=body) for _ in range(3)], False),
    ]
    for index, (items, expected) in enumerate(cases):
        filled = section.model_copy(update={"items": items})
        fits = [m for m in _render(filled, tmp_path / str(index)).facts.marks if m.kind == "fit"]
        assert fits
        assert all(mark.ok for mark in fits) is expected


def test_D5_fixture_deck_check_is_clean(tmp_path, capsys):
    _manifests()
    source = tmp_path / "deck.md"
    assert serialiser is not None and hasattr(serialiser, "serialise")
    assert cli is not None and hasattr(cli, "main")
    source.write_text(serialiser.serialise(_document(_fixture())), encoding="utf-8")
    try:
        code = cli.main(["check", str(source), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    assert code == 0, (captured.out, captured.err)
    assert "no findings" in captured.out.splitlines()


def test_D6_matrix_source_has_no_colour_literals():
    path = ROOT / "src/docla/render/library/matrix.typ"
    assert path.is_file(), "matrix.typ must exist"
    source = path.read_text(encoding="utf-8")
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", source)
