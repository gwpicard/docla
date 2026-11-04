# Intent: the cover component routes, renders and honours its declared capacity.
import importlib
import importlib.util
import re
from pathlib import Path

import yaml

from docla.model import Document, Item, Section


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name or ""
        if missing != name and not missing.startswith(name + "."):
            raise
        if missing != name and importlib.util.find_spec(missing) is not None:
            raise
        return None


components = _optional("docla.render.components")
chooser_module = _optional("docla.render.chooser")
swatch_module = _optional("docla.render.swatch")
theme_module = _optional("docla.theme")
source_module = _optional("docla.source")
cli = _optional("docla.cli")
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/cover.yaml"


def _fixture():
    assert FIXTURE.is_file(), "cover fixture must exist"
    return Section.model_validate(yaml.safe_load(FIXTURE.read_text(encoding="utf-8")))


def _document(section):
    return Document(front={"doctype": "pitch-deck", "title": "Cover"}, format="slides", sections=[section])


def _render(section, tmp_path):
    assert swatch_module is not None and hasattr(swatch_module, "swatch"), "swatch must exist"
    assert theme_module is not None and hasattr(theme_module, "neutral_theme"), "neutral_theme must exist"
    assert chooser_module is not None and hasattr(chooser_module, "load_chooser"), "load_chooser must exist"
    assert chooser_module.load_chooser().knows("cover", "slides"), "cover route must exist"
    return swatch_module.swatch(_document(section), section.id, tmp_path, theme=theme_module.neutral_theme())


def test_D1_cover_manifest_and_packaged_components():
    assert components is not None and hasattr(components, "all_manifests"), "all_manifests must exist"
    assert hasattr(components, "load_manifests"), "load_manifests must exist"
    manifests = components.all_manifests()
    assert "cover" in manifests
    cover = manifests["cover"]
    assert cover.name == "cover"
    assert cover.format == "slides"
    assert cover.intents == ["cover"]
    assert cover.capacity == {"title_words": (1, 12), "paragraphs": (0, 1)}
    assert cover.elements == ["title", "subtitle", "panel"]
    assert cover.label.strip()
    assert set(components.load_manifests()) == {"statement", "bullets", "body", "callout"}


def test_D2_chooser_routes_cover_and_pinned_components():
    assert chooser_module is not None and hasattr(chooser_module, "load_chooser"), "load_chooser must exist"
    chooser = chooser_module.load_chooser()
    assert chooser.knows("cover", "slides"), "cover route must exist"
    cases = [
        (Section(id="a", intent="cover", title="Opening"), "slides", "cover"),
        (Section(id="b", intent="statement", title="Claim"), "slides", "statement"),
        (Section(id="c", intent="bullets", items=[Item(body="Point") for _ in range(3)]), "slides", "bullets"),
        (Section(id="d", intent="body", title="Title", paragraphs=["Text"]), "doc", "body"),
        (Section(id="e", intent="callout", title="Title", items=[Item(body="Point")]), "doc", "callout"),
    ]
    for section, fmt, expected in cases:
        assert chooser.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_renders_one_marked_slide(tmp_path):
    section = _fixture()
    assert section.intent == "cover"
    assert section.title and section.paragraphs
    result = _render(section, tmp_path)
    assert [(page.width, page.height) for page in result.facts.pages] == [(960, 540)]
    assert {(m.id, m.edge) for m in result.facts.marks if m.kind == "section"} == {
        (section.id, "start"), (section.id, "end")
    }
    assert {m.role for m in result.facts.marks if m.kind == "element" and m.id == section.id} >= {
        "title", "subtitle", "panel"
    }


def test_D4_title_capacity_has_a_real_fit_boundary(tmp_path):
    for count, expected in [(12, True), (13, False)]:
        section = Section(id="cover1", intent="cover", title=" ".join(["seventy"] * count))
        result = _render(section, tmp_path / str(count))
        fits = [mark for mark in result.facts.marks if mark.kind == "fit"]
        assert fits, "cover must emit fit marks"
        assert all(mark.ok for mark in fits) is expected


def test_D5_check_fixture_deck_has_no_findings(tmp_path, capsys):
    assert source_module is not None and hasattr(source_module, "serialise"), "serialise must exist"
    assert cli is not None and hasattr(cli, "main"), "cli.main must exist"
    path = tmp_path / "deck.md"
    path.write_text(source_module.serialise(_document(_fixture())), encoding="utf-8")
    try:
        code = cli.main(["check", str(path), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr()
    assert code == 0, (output.out, output.err)
    assert "no findings" in output.out.splitlines()


def test_D6_cover_has_no_colour_literals():
    path = ROOT / "src/docla/render/library/cover.typ"
    assert path.is_file(), "cover.typ must exist"
    text = path.read_text(encoding="utf-8")
    assert re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", text) is None
