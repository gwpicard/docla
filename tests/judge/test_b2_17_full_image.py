# Intent: full-image routes and renders a full-frame image with a caption at its stated capacity.
import importlib.util
import json
import re
from pathlib import Path

import yaml
from PIL import Image

from docla.model import Document, Item, Section
from docla.render import chooser, compose, marks, typst
from docla.source.serialiser import serialise
from docla.theme import neutral_theme

try:
    from docla.render import components
except ImportError as error:
    if error.name not in ("docla.render.components",):
        raise
    if importlib.util.find_spec(error.name) is not None:
        raise
    components = None

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/full-image.yaml"
SOURCE = ROOT / "src/docla/render/library/full-image.typ"


def _manifests():
    assert components is not None and hasattr(components, "all_manifests"), (
        "docla.render.components.all_manifests must exist"
    )
    return components.all_manifests()


def _fixture():
    assert FIXTURE.is_file(), "full-image fixture must exist"
    sec = Section.model_validate(yaml.safe_load(FIXTURE.read_text()))
    assert sec.id and sec.intent == "full-image"
    assert sec.image and not Path(sec.image).is_absolute() and ".." not in Path(sec.image).parts
    assert len(sec.paragraphs) == 1 and sec.paragraphs[0]
    return sec


def _asset(root, sec):
    path = root / sec.image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (80, 45), (80, 120, 160)).save(path, format="PNG")


def _render(tmp_path, sec):
    route = chooser.load_chooser(manifests=_manifests())
    assert route.knows("full-image", "slides"), "the chooser must have slides entries for intent full-image"
    doc = Document(front={}, format="slides", sections=[sec])
    assets = tmp_path / "assets"
    _asset(assets, sec)
    comp = compose.compose(doc, chooser=route, assets=[assets])
    assert [s.component for s in comp.sections] == ["full-image"]
    dest = tmp_path / "render"
    dest.parent.mkdir(parents=True, exist_ok=True)
    main = compose.assemble(comp, dest, theme=neutral_theme())
    content = json.loads((dest / "composition.json").read_text())["sections"][0]["content"]
    image_path = content["image"]
    assert image_path.startswith("/assets/") and (dest / image_path.lstrip("/")).is_file()
    fonts = compose.font_paths(dest)
    pdf = dest / "page.pdf"
    typst.compile_pdf(main, dest, pdf, fonts)
    from docla.facts.layout import layout_facts

    return layout_facts(pdf, main, dest, font_paths=fonts)


def test_D1_full_image_manifest_and_original_packaged_components():
    manifests = _manifests()
    assert "full-image" in manifests
    manifest = manifests["full-image"]
    assert manifest.name == "full-image"
    assert manifest.format == "slides"
    assert list(manifest.intents) == ["full-image"]
    assert {k: tuple(v) for k, v in manifest.capacity.items()} == {"title_words": (0, 8), "paragraphs": (0, 1)}
    assert list(manifest.elements) == ["image", "caption"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_chooser_routes_image_and_preserves_m1_routes():
    route = chooser.load_chooser(manifests=_manifests())
    assert route.knows("full-image", "slides"), "the chooser must have slides entries for intent full-image"
    assert route.choose(Section(id="a", intent="full-image", image="assets/photo.png"), "slides", 0, 1) == "full-image"
    assert route.choose(Section(id="a", intent="full-image"), "slides", 0, 1) == "statement"
    cases = [
        ("slides", Section(id="a", intent="statement", title="Claim"), "statement"),
        ("slides", Section(id="b", intent="bullets", items=[Item(body="Point")] * 3), "bullets"),
        ("doc", Section(id="c", intent="body", title="Title", paragraphs=["Text"]), "body"),
        ("doc", Section(id="d", intent="callout", title="Title", items=[Item(body="Point")]), "callout"),
    ]
    for fmt, section, expected in cases:
        assert route.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_marks(tmp_path):
    sec = _fixture()
    facts = _render(tmp_path, sec)
    assert [(page.width, page.height) for page in facts.pages] == [(960, 540)]
    sections = [m for m in facts.marks if isinstance(m, marks.SectionMark)]
    assert [(m.id, m.edge) for m in sections] == [(sec.id, "start"), (sec.id, "end")]
    elements = [m for m in facts.marks if isinstance(m, marks.ElementMark)]
    assert {m.role for m in elements if m.id == sec.id} >= {"image", "caption"}
    image = [m for m in elements if m.id == sec.id and m.role == "image"]
    assert any(m.w >= 480 and m.h >= 270 for m in image)


def test_D4_caption_capacity_boundary(tmp_path):
    sec = _fixture()
    for length, expected in [(100, True), (101, False)]:
        sample = sec.model_copy(update={"paragraphs": ["x" * length]})
        facts = _render(tmp_path / str(length), sample)
        fits = [m for m in facts.marks if isinstance(m, marks.FitMark)]
        assert fits, "full-image must report fit marks"
        assert all(m.ok for m in fits) is expected


def test_D5_check_fixture_deck_has_no_findings(tmp_path, capsys):
    from docla import cli

    _manifests()
    sec = _fixture()
    _asset(tmp_path / "assets", sec)
    doc = Document(front={"doctype": "pitch-deck", "format": "slides", "title": "Deck"}, format="slides", sections=[sec])
    source = tmp_path / "deck.md"
    source.write_text(serialise(doc))
    try:
        code = cli.main(["check", str(source), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr()
    assert code == 0, (output.out, output.err)
    assert output.out.splitlines() == ["no findings"]


def test_D6_full_image_source_has_no_colour_literals():
    assert SOURCE.is_file(), "full-image.typ must exist"
    text = SOURCE.read_text()
    assert re.search(r"\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b", text) is None
