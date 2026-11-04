# Intent: table sections route to a themed slide component with truthful capacity and marked content.
import re
from pathlib import Path

import yaml

from docla import cli, source, theme
from docla.model import Document, Item, Section
from docla.render import chooser, components, swatch

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/table.yaml"
TABLE = ROOT / "src/docla/render/library/table.typ"


def _manifests():
    assert hasattr(components, "all_manifests"), "docla.render.components.all_manifests must exist"
    manifests = components.all_manifests()
    assert "table" in manifests, "table manifest must exist"
    return manifests


def _fixture():
    assert FIXTURE.is_file(), "table fixture must exist"
    return Section.model_validate(yaml.safe_load(FIXTURE.read_text(encoding="utf-8")))


def _document(section):
    return Document(front={"doctype": "pitch-deck", "title": "Table", "theme": "neutral"}, format="slides", sections=[section])


def _render(section, tmp_path):
    _manifests()
    assert hasattr(theme, "neutral_theme"), "neutral_theme must exist"
    tmp_path.mkdir(parents=True, exist_ok=True)
    return swatch.swatch(_document(section), section.id, tmp_path, theme=theme.neutral_theme())


def test_D1_table_manifest_and_original_packaged_components():
    table = _manifests()["table"]
    assert table.name == "table"
    assert table.format == "slides"
    assert table.intents == ["table"]
    assert table.capacity == {"title_words": (1, 8), "columns": (2, 6), "rows": (1, 10)}
    assert table.elements == ["title", "table-header", "table-cell", "figure", "figure-source"]
    assert table.label.strip()
    assert set(components.load_manifests()) == {"statement", "bullets", "body", "callout"}


def test_D2_table_and_pinned_routes():
    routes = chooser.load_chooser(manifests=_manifests())
    table = Section(id="table", intent="table", title="Results", data={"columns": ["A", "B"], "rows": [["1", "2"]]})
    assert routes.choose(table, "slides", 0, 1) == "table"
    assert routes.choose(table.model_copy(update={"data": None}), "slides", 0, 1) == "bullets"
    cases = [
        (Section(id="a", intent="statement", title="Claim"), "slides", "statement"),
        (Section(id="b", intent="bullets", items=[Item(body="Point")] * 3), "slides", "bullets"),
        (Section(id="c", intent="body", paragraphs=["Text"]), "doc", "body"),
        (Section(id="d", intent="callout", paragraphs=["Text"]), "doc", "callout"),
    ]
    for section, fmt, expected in cases:
        assert routes.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_marks(tmp_path):
    section = _fixture()
    result = _render(section, tmp_path)
    assert [(page.width, page.height) for page in result.facts.pages] == [(960, 540)]
    assert {(m.id, m.edge) for m in result.facts.marks if m.kind == "section"} == {
        (section.id, "start"), (section.id, "end")
    }
    roles = {m.role for m in result.facts.marks if m.kind == "element" and m.id == section.id}
    assert {"title", "table-header", "table-cell", "figure", "figure-source"} <= roles


def test_D4_capacity_boundary_has_truthful_fit_marks(tmp_path):
    section = _fixture()
    data = {"columns": [f"Col {n}" for n in range(1, 7)], "rows": [["Value"] * 6 for _ in range(10)]}
    at_limit = _render(section.model_copy(update={"data": data}), tmp_path / "limit")
    fits = [m for m in at_limit.facts.marks if m.kind == "fit"]
    assert fits and all(m.ok for m in fits)
    data = {**data, "rows": data["rows"] + [["Value"] * 6]}
    over = _render(section.model_copy(update={"data": data}), tmp_path / "over")
    fits = [m for m in over.facts.marks if m.kind == "fit"]
    assert fits and any(not m.ok for m in fits)


def test_D5_check_fixture_deck_has_no_findings(tmp_path, capsys):
    _manifests()
    section = _fixture()
    assert section.intent == "table"
    path = tmp_path / "deck.md"
    path.write_text(source.serialise(_document(section)), encoding="utf-8")
    try:
        code = cli.main(["check", str(path), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr()
    assert code == 0, (output.out, output.err)
    assert "no findings" in output.out.splitlines()


def test_D6_table_source_has_no_colour_literals():
    assert TABLE.is_file(), "table.typ must exist"
    text = TABLE.read_text(encoding="utf-8")
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", text)
