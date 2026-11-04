# Intent: chapter-break routes and renders a clean, capacity-bounded slide using its library manifest.
import re
from pathlib import Path

import yaml

from docla.model import Document, Item, Section
from docla.render import chooser, swatch
from docla.source.serialiser import serialise
from docla.theme import neutral_theme

ROOT = Path(__file__).resolve().parents[2]

try:
    from docla.render import components
except ImportError as error:
    if error.name not in ("docla.render.components",):
        raise
    components = None


def _manifests():
    assert components is not None and hasattr(components, "all_manifests"), (
        "docla.render.components.all_manifests must exist"
    )
    manifests = components.all_manifests()
    assert "chapter-break" in manifests, "chapter-break manifest must exist"
    return manifests


def _fixture():
    _manifests()
    path = ROOT / "tests/fixtures/components/chapter-break.yaml"
    assert path.is_file(), "chapter-break fixture must exist"
    return Section.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _document(section):
    return Document(front={"doctype": "pitch-deck", "title": "Deck"}, format="slides", sections=[section])


def _render(section, tmp_path):
    _manifests()
    assert section.id
    return swatch.swatch(_document(section), section.id, tmp_path, theme=neutral_theme())


def test_D1_manifest_and_packaged_components():
    manifest = _manifests()["chapter-break"]
    assert manifest.name == "chapter-break"
    assert manifest.format == "slides"
    assert list(manifest.intents) == ["chapter-break"]
    assert {k: tuple(v) for k, v in manifest.capacity.items()} == {
        "title_words": (1, 10), "paragraphs": (0, 1)
    }
    assert list(manifest.elements) == ["title", "number"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_packaged_chooser_routes_chapter_and_pinned_components():
    table = chooser.load_chooser(manifests=_manifests())
    cases = [
        (Section(id="a", intent="chapter-break", title="Chapter"), "slides", "chapter-break"),
        (Section(id="b", intent="statement", title="Claim"), "slides", "statement"),
        (Section(id="c", intent="bullets", items=[Item(body="A point") for _ in range(3)]), "slides", "bullets"),
        (Section(id="d", intent="body", paragraphs=["Text"]), "doc", "body"),
        (Section(id="e", intent="callout", items=[Item(body="A point")]), "doc", "callout"),
    ]
    for section, fmt, expected in cases:
        assert table.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_marks(tmp_path):
    section = _fixture()
    assert section.intent == "chapter-break"
    assert section.title and section.paragraphs
    result = _render(section, tmp_path)
    assert [(page.width, page.height) for page in result.facts.pages] == [(960, 540)]
    marks = result.facts.marks
    assert {(m.id, m.edge) for m in marks if m.kind == "section"} == {
        (section.id, "start"), (section.id, "end")
    }
    assert {m.role for m in marks if m.kind == "element" and m.id == section.id} >= {"title", "number"}


def test_D4_title_capacity_boundary(tmp_path):
    section = _fixture()
    ten = "one two three four five six seven eight nine ten"
    for title, expected in [(ten, True), (ten + " eleven", False)]:
        result = _render(section.model_copy(update={"title": title}), tmp_path)
        fits = [m.ok for m in result.facts.marks if m.kind == "fit"]
        assert fits
        assert all(fits) is expected


def test_D5_fixture_deck_checks_clean(tmp_path, capsys):
    from docla import cli

    section = _fixture()
    source = tmp_path / "deck.md"
    source.write_text(serialise(_document(section)), encoding="utf-8")
    assert hasattr(cli, "main"), "docla.cli.main must exist"
    try:
        code = cli.main(["check", str(source), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    assert "no findings" in captured.out.splitlines()
    assert "geo.palette" not in captured.out


def test_D6_component_has_no_colour_literals():
    _manifests()
    path = ROOT / "src/docla/render/library/chapter-break.typ"
    assert path.is_file(), "chapter-break Typst component must exist"
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", text)
