# Intent: image-with-text renders and routes image and text within its slide capacity.
import importlib
import re
from pathlib import Path

import yaml
from PIL import Image

from docla.model import Document, Item, Section


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not str(error.name).startswith(name + "."):
            raise
        return None


components = _optional("docla.render.components")
chooser_module = _optional("docla.render.chooser")
compose_module = _optional("docla.render.compose")
theme_module = _optional("docla.theme")
cli = _optional("docla.cli")
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/image-with-text.yaml"


def _manifests():
    assert components is not None and hasattr(components, "all_manifests"), "all_manifests must exist"
    return components.all_manifests()


def _chooser():
    assert chooser_module is not None and hasattr(chooser_module, "load_chooser")
    routes = chooser_module.load_chooser(manifests=_manifests())
    assert routes.knows("image-text", "slides"), "the chooser must have slides entries for intent image-text"
    return routes


def _fixture():
    assert FIXTURE.is_file(), "image-with-text fixture must exist"
    section = Section.model_validate(yaml.safe_load(FIXTURE.read_text()))
    assert section.id and section.image and section.items and section.title
    assert section.intent == "image-text"
    return section


def _assets(tmp_path, section):
    assets = tmp_path / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    path = assets / section.image
    assert path.resolve().is_relative_to(assets.resolve()) and path.suffix.lower() == ".png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), (40, 100, 160)).save(path)
    return assets


def _render(tmp_path, section):
    from docla.facts.layout import layout_facts
    from docla.render.typst import compile_pdf

    assert compose_module is not None and hasattr(compose_module, "compose") and hasattr(compose_module, "assemble")
    assert theme_module is not None and hasattr(theme_module, "neutral_theme")
    assets = _assets(tmp_path, section)
    doc = Document(front={"title": "Deck"}, format="slides", sections=[section])
    comp = compose_module.compose(doc, chooser=_chooser(), assets=[assets])
    assert [s.component for s in comp.sections] == ["image-with-text"]
    dest = tmp_path / "render"
    main = compose_module.assemble(comp, dest, theme=theme_module.neutral_theme())
    fonts = compose_module.font_paths(dest)
    pdf = dest / "slide.pdf"
    compile_pdf(main, dest, pdf, fonts)
    return layout_facts(pdf, main, dest, font_paths=fonts)


def test_D1_manifest_and_packaged_components():
    manifests = _manifests()
    assert "image-with-text" in manifests
    manifest = manifests["image-with-text"]
    assert manifest.name == "image-with-text"
    assert manifest.format == "slides"
    assert list(manifest.intents) == ["image-text"]
    assert {key: tuple(value) for key, value in manifest.capacity.items()} == {
        "title_words": (1, 8), "items": (1, 5), "item_chars": (10, 80)
    }
    assert list(manifest.elements) == ["image", "title", "item"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_chooser_routes_image_and_preserves_pinned_routes():
    chooser = _chooser()
    section = Section(id="img", intent="image-text", title="A title", image="picture.png", items=[Item(body="A useful point")])
    assert chooser.choose(section, "slides", 0, 1) == "image-with-text"
    assert chooser.choose(section.model_copy(update={"image": None}), "slides", 0, 1) == "bullets"
    cases = [
        ("slides", Section(id="a", intent="statement", title="Claim"), "statement"),
        ("slides", Section(id="b", intent="bullets", items=[Item(body="A useful point")] * 3), "bullets"),
        ("doc", Section(id="c", intent="body", title="Title", paragraphs=["Text"]), "body"),
        ("doc", Section(id="d", intent="callout", title="Title", items=[Item(body="A useful point")]), "callout"),
    ]
    for fmt, value, expected in cases:
        assert chooser.choose(value, fmt, 0, 1) == expected


def test_D3_fixture_renders_page_and_marks(tmp_path):
    section = _fixture()
    facts = _render(tmp_path, section)
    assert [(page.width, page.height) for page in facts.pages] == [(960, 540)]
    assert {(m.id, m.edge) for m in facts.marks if m.kind == "section"} == {(section.id, "start"), (section.id, "end")}
    assert {m.role for m in facts.marks if m.kind == "element" and m.id == section.id} >= {"image", "title", "item"}


def test_D4_capacity_boundary_reports_overflow(tmp_path):
    section = _fixture()
    body = "A useful point " * 5 + "words"
    assert len(body) == 80
    maximum = section.model_copy(update={"items": [Item(body=body) for _ in range(5)]})
    fits = [m for m in _render(tmp_path / "max", maximum).marks if m.kind == "fit"]
    assert fits and all(m.ok for m in fits)
    overflow = maximum.model_copy(update={"items": [Item(body=body) for _ in range(6)]})
    fits = [m for m in _render(tmp_path / "over", overflow).marks if m.kind == "fit"]
    assert fits and any(not m.ok for m in fits)


def test_D5_check_fixture_has_no_findings(tmp_path, capsys):
    from docla.source import serialise

    assert cli is not None and hasattr(cli, "main")
    section = _fixture()
    _assets(tmp_path, section)
    doc = Document(front={"doctype": "pitch-deck", "title": "Deck"}, format="slides", sections=[section])
    source = tmp_path / "deck.md"
    source.write_text(serialise(doc))
    try:
        code = cli.main(["check", str(source), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr()
    assert code == 0, (output.out, output.err)
    assert "no findings" in output.out.splitlines()


def test_D6_no_colour_literals():
    path = ROOT / "src/docla/render/library/image-with-text.typ"
    assert path.is_file(), "image-with-text Typst component must exist"
    assert not re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", path.read_text())
