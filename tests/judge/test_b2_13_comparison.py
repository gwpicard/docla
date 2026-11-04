# Intent: comparison sections render as capacity-aware columns through the packaged library.
import importlib
import importlib.util
import re
from pathlib import Path

import pytest
import yaml

from docla.model import Document, Item, Section, Source
from docla.render.marks import ElementMark, FitMark, SectionMark


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name
        if missing and (missing == name or name.startswith(missing + ".")):
            if importlib.util.find_spec(missing) is None:
                return None
        raise


components = _module("docla.render.components")
chooser_module = _module("docla.render.chooser")
swatch_module = _module("docla.render.swatch")
theme_module = _module("docla.theme")
source_module = _module("docla.source")
cli = _module("docla.cli")
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/comparison.yaml"


def _manifests():
    assert components is not None and hasattr(components, "all_manifests"), "all_manifests must exist"
    return components.all_manifests()


def _fixture():
    assert FIXTURE.is_file(), "comparison fixture must exist"
    section = Section.model_validate(yaml.safe_load(FIXTURE.read_text()))
    assert section.id and section.intent == "comparison"
    return section


def _render(section, tmp_path):
    assert swatch_module is not None and hasattr(swatch_module, "swatch")
    assert theme_module is not None and hasattr(theme_module, "neutral_theme")
    assert "comparison" in _manifests()
    tmp_path.mkdir(parents=True, exist_ok=True)
    doc = Document(front={"title": "Comparison"}, format="slides", sections=[section])
    return swatch_module.swatch(doc, section.id, tmp_path, theme=theme_module.neutral_theme())


def test_D1_comparison_manifest_and_packaged_components():
    manifests = _manifests()
    assert "comparison" in manifests
    manifest = manifests["comparison"]
    assert manifest.name == "comparison"
    assert manifest.format == "slides"
    assert list(manifest.intents) == ["comparison"]
    assert {key: tuple(value) for key, value in manifest.capacity.items()} == {
        "title_words": (1, 8), "items": (2, 3), "item_chars": (3, 40), "rows": (0, 4)
    }
    assert list(manifest.elements) == ["title", "column-title", "row"]
    assert isinstance(manifest.label, str) and manifest.label.strip()
    assert hasattr(components, "load_manifests")
    assert set(components.load_manifests()) == {"statement", "bullets", "body", "callout"}


@pytest.mark.parametrize("count, expected", [(2, "comparison"), (3, "comparison"), (4, "two-column")])
def test_D2_comparison_count_routes(count, expected):
    manifests = _manifests()
    assert chooser_module is not None and hasattr(chooser_module, "load_chooser")
    chooser = chooser_module.load_chooser(manifests=manifests)
    assert chooser.knows("comparison", "slides"), "the chooser must have slides entries for intent comparison"
    section = Section(id="s1", intent="comparison", items=[Item(head="Option", body="") for _ in range(count)])
    assert chooser.choose(section, "slides", 0, 1) == expected


def test_D2_existing_routes_stay():
    assert chooser_module is not None and hasattr(chooser_module, "load_chooser")
    chooser = chooser_module.load_chooser(manifests=_manifests())
    assert chooser.knows("comparison", "slides"), "the chooser must have slides entries for intent comparison"
    cases = [
        (Section(id="s1", intent="statement", title="Claim"), "slides", "statement"),
        (Section(id="s2", intent="bullets", items=[Item(body="A useful point") for _ in range(3)]), "slides", "bullets"),
        (Section(id="s3", intent="body", paragraphs=["Text"]), "doc", "body"),
        (Section(id="s4", intent="callout", items=[Item(body="A useful point")]), "doc", "callout"),
    ]
    for section, fmt, expected in cases:
        assert chooser.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_marks(tmp_path):
    section = _fixture()
    assert section.title and section.items and all(item.head and item.sub for item in section.items)
    facts = _render(section, tmp_path).facts
    assert len(facts.pages) == 1
    assert (facts.pages[0].width, facts.pages[0].height) == (960, 540)
    assert {m.edge for m in facts.marks if isinstance(m, SectionMark) and m.id == section.id} == {"start", "end"}
    roles = {m.role for m in facts.marks if isinstance(m, ElementMark) and m.id == section.id}
    assert {"title", "column-title", "row"} <= roles


def test_D4_row_capacity_boundary(tmp_path):
    def section(rows):
        return Section(id="s1", intent="comparison", title="Compare options", items=[
            Item(head=head, body="", sub=["Short row"] * rows) for head in ("Alpha", "Bravo", "Charlie")
        ])

    fits = [m for m in _render(section(4), tmp_path / "within").facts.marks if isinstance(m, FitMark)]
    assert fits and all(m.ok for m in fits)
    overflow = [m for m in _render(section(5), tmp_path / "over").facts.marks if isinstance(m, FitMark)]
    assert overflow and any(not m.ok for m in overflow)


def test_D5_fixture_working_file_checks_cleanly(tmp_path, capsys):
    section = _fixture()
    assert source_module is not None and hasattr(source_module, "serialise")
    assert cli is not None and hasattr(cli, "main")
    assert "comparison" in _manifests()
    keys = sorted({citation.key for item in section.items for citation in item.citations})
    doc = Document(front={"doctype": "pitch-deck", "title": "Comparison"}, format="slides",
                   sources=[Source(key=key, text="Reference") for key in keys], sections=[section])
    path = tmp_path / "deck.md"
    path.write_text(source_module.serialise(doc))
    try:
        code = cli.main(["check", str(path), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    assert code == 0, (captured.out, captured.err)
    assert captured.out.splitlines() == ["no findings"]


def test_D6_comparison_source_has_no_colour_literals():
    path = ROOT / "src/docla/render/library/comparison.typ"
    assert path.is_file(), "comparison.typ must exist"
    text = path.read_text()
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", text)
