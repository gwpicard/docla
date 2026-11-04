# Intent: matrix sections render as marked slides within their advertised capacity.
import re
from pathlib import Path

import yaml

from docla import cli
from docla.model import Document, Item, Section
from docla.render import chooser, components, swatch
from docla.source.serialiser import serialise
from docla.theme import neutral_theme

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/matrix.yaml"


def _manifests():
    assert hasattr(components, "all_manifests"), "docla.render.components.all_manifests must exist"
    manifests = components.all_manifests()
    assert "matrix" in manifests, "matrix manifest must exist"
    return manifests


def _fixture():
    assert FIXTURE.is_file(), "matrix fixture must exist"
    section = Section.model_validate(yaml.safe_load(FIXTURE.read_text(encoding="utf-8")))
    assert section.id and section.intent == "matrix"
    return section


def _document(section):
    return Document(front={"doctype": "pitch-deck", "title": "Matrix"}, format="slides", sections=[section])


def _render(section, tmp_path):
    _manifests()
    return swatch.swatch(_document(section), section.id, tmp_path, theme=neutral_theme())


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
    routing = chooser.load_chooser(manifests=_manifests())
    cases = [
        (Section(id="m", intent="matrix", items=[Item(body="A quadrant") for _ in range(4)]), "slides", "matrix"),
        (Section(id="s", intent="statement", title="Claim"), "slides", "statement"),
        (Section(id="b", intent="bullets", items=[Item(body="A point") for _ in range(3)]), "slides", "bullets"),
        (Section(id="d", intent="body", paragraphs=["A paragraph"]), "doc", "body"),
        (Section(id="c", intent="callout", items=[Item(body="A callout")]), "doc", "callout"),
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


def test_D4_capacity_boundary_is_reflected_in_fit_marks(tmp_path):
    section = _fixture()
    text = "word " * 14
    assert len(text) == 70
    for length, expected in [(70, True), (71, False)]:
        body = text if length == 70 else text + "x"
        filled = section.model_copy(update={"items": [Item(body=body) for _ in range(4)]})
        fits = [m for m in _render(filled, tmp_path / str(length)).facts.marks if m.kind == "fit"]
        assert fits
        assert all(mark.ok for mark in fits) is expected


def test_D5_fixture_deck_check_is_clean(tmp_path, capsys):
    _manifests()
    source = tmp_path / "deck.md"
    source.write_text(serialise(_document(_fixture())), encoding="utf-8")
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
