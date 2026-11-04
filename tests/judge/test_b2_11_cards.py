# Intent: cards renders parallel sets within its declared slide capacity.
import re
from pathlib import Path

import pytest
import yaml

try:
    from docla import cli, model, source, theme
    from docla.render import chooser, components, swatch
except ImportError as error:
    if error.name not in {
        "docla", "docla.cli", "docla.model", "docla.source", "docla.theme", "docla.render",
        "docla.render.chooser", "docla.render.components", "docla.render.swatch",
    }:
        raise
    cli = model = source = theme = chooser = components = swatch = None

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/cards.yaml"


def _manifests():
    assert components is not None and hasattr(components, "all_manifests"), "all_manifests must exist"
    return components.all_manifests()


def _section(count, length=30):
    body = ("word " * ((length + 4) // 5))[:length]
    return model.Section(id="cards1", intent="parallel-set", title="Parallel choices", component="cards",
                         items=[model.Item(body=body) for _ in range(count)])


def _fixture():
    assert FIXTURE.is_file(), "cards fixture must exist"
    return model.Section.model_validate(yaml.safe_load(FIXTURE.read_text()))


def _render(section, tmp_path):
    assert "cards" in _manifests(), "cards manifest must exist"
    assert section.id
    doc = model.Document(front={"title": "Cards"}, format="slides", sections=[section])
    return swatch.swatch(doc, section.id, tmp_path, theme=theme.neutral_theme())


def test_D1_cards_manifest_and_packaged_components():
    manifests = _manifests()
    assert "cards" in manifests
    cards = manifests["cards"]
    assert cards.name == "cards"
    assert cards.format == "slides"
    assert list(cards.intents) == ["parallel-set"]
    assert {k: tuple(v) for k, v in cards.capacity.items()} == {
        "title_words": (1, 8), "items": (2, 4), "item_chars": (10, 100)
    }
    assert list(cards.elements) == ["title", "item"]
    assert cards.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_packaged_chooser_routes_and_pinned_routes():
    routes = chooser.load_chooser(manifests=_manifests())
    assert routes.knows("parallel-set", "slides"), "the chooser must have slides entries for intent parallel-set"
    for count, expected in [(1, "bullets"), (2, "cards"), (3, "cards"), (4, "cards"), (5, "bullets")]:
        assert routes.choose(_section(count), "slides", 0, 1) == expected
    for fmt, section, expected in [
        ("slides", model.Section(id="s", intent="statement", title="Claim"), "statement"),
        ("slides", model.Section(id="b", intent="bullets", items=[model.Item(body="Point")] * 3), "bullets"),
        ("doc", model.Section(id="d", intent="body", paragraphs=["Text"]), "body"),
        ("doc", model.Section(id="c", intent="callout", items=[model.Item(body="Text")]), "callout"),
    ]:
        assert routes.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_marks(tmp_path):
    section = _fixture()
    assert section.intent == "parallel-set" and section.title and 2 <= len(section.items) <= 4
    result = _render(section, tmp_path)
    assert len(result.facts.pages) == 1
    page = result.facts.pages[0]
    assert (page.width, page.height) == (960, 540)
    marks = result.facts.marks
    assert {(m.id, m.edge) for m in marks if m.kind == "section"} == {(section.id, "start"), (section.id, "end")}
    assert {m.role for m in marks if m.kind == "element" and m.id == section.id} >= {"title", "item"}
    assert len([m for m in marks if m.kind == "element" and m.id == section.id and m.role == "item"]) >= len(section.items)


@pytest.mark.parametrize("count,length,expected", [(4, 100, True), (4, 101, False), (5, 100, False)])
def test_D4_capacity_fit_marks(tmp_path, count, length, expected):
    result = _render(_section(count, length), tmp_path)
    fits = [m for m in result.facts.marks if m.kind == "fit"]
    assert fits, "cards must emit fit marks"
    assert all(m.ok for m in fits) is expected


def test_D5_fixture_deck_check_has_no_findings(tmp_path, capsys):
    _manifests()
    section = _fixture()
    doc = model.Document(front={"doctype": "pitch-deck", "title": "Cards"}, format="slides", sections=[section])
    path = tmp_path / "deck.md"
    path.write_text(source.serialise(doc))
    code = cli.main(["check", str(path), "--out", str(tmp_path / "out")])
    output = capsys.readouterr()
    assert code == 0, output.out + output.err
    assert "no findings" in output.out.lower()


def test_D6_cards_typ_has_no_colour_literals():
    path = ROOT / "src/docla/render/library/cards.typ"
    assert path.is_file(), "cards.typ must exist"
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", path.read_text())


@pytest.mark.parametrize("rule", ["source.citations-resolve", "source.empty-section"])
def test_D7_seeded_source_findings_still_reported(tmp_path, capsys, rule):
    path = ROOT / "tests/fixtures/seeded-defects" / rule / "fail/doc.md"
    assert path.is_file()
    code = cli.main(["check", str(path), "--out", str(tmp_path / "out")])
    output = capsys.readouterr()
    assert code == 1
    assert any(line.startswith(f"error {rule} ") for line in output.out.splitlines())
