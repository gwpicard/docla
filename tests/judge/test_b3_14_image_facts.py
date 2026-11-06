# Intent: Layout facts expose placed images and their effective resolution without changing existing facts.
import importlib
import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from PIL import Image


def _subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name
        if not missing or not (missing == name or name.startswith(missing + ".") or missing.startswith(name + ".")):
            raise
        try:
            spec = importlib.util.find_spec(missing)
        except ModuleNotFoundError:
            spec = None
        if spec is not None:
            raise
        return None


models = _subject("docla.facts.models")
layout = _subject("docla.facts.layout")
pdf_module = _subject("docla.facts.pdf")
marks = _subject("docla.render.marks")
swatch = _subject("docla.render.swatch")
model = _subject("docla.model")
theme = _subject("docla.theme")
golden = _subject("docla.testing.golden")
cli = _subject("docla.cli")
compose = _subject("docla.render.compose")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "components"

SLIDES = """---
doctype: pitch-deck
format: slides
title: Readout
---

## Sources

- [S1] workshop.vtt, transcript

::: {#aaaa1 .section intent="statement"}
## One pilot is enough
:::

::: {#aaaa2 .section intent="bullets"}
## Why it works

- Short intervals catch drift early. [S1 00:41]
- Cheap to repeat.
:::
"""


def _image_interface():
    assert models is not None and hasattr(models, "ImageFact"), "ImageFact must exist"
    assert layout is not None and hasattr(layout, "PlacedImage"), "PlacedImage must exist"


def _render_image(tmp_path):
    assert swatch is not None and hasattr(swatch, "swatch")
    assert model is not None and theme is not None
    section = model.Section.model_validate(yaml.safe_load((FIXTURES / "image-with-text.yaml").read_text()))
    assets = tmp_path / "assets"
    assets.mkdir()
    Image.new("RGB", (320, 240), "blue").save(assets / section.image)
    doc = model.Document(front={}, format="slides", sections=[section])
    return swatch.swatch(doc, section.id, tmp_path, theme.neutral_theme(), assets=[assets])


def test_D1_image_types_and_default_lists():
    _image_interface()
    assert set(models.ImageFact.model_fields) == {"box", "native_w", "native_h", "dpi_x", "dpi_y"}
    assert set(layout.PlacedImage.model_fields) == {
        "box",
        "native_w",
        "native_h",
        "dpi_x",
        "dpi_y",
        "role",
        "section_id",
    }
    assert issubclass(layout.PlacedImage, models.ImageFact)
    page = models.PageFacts(page=1, width=960, height=540, words=[], shapes=[])
    facts = layout.LayoutFacts(pdf_sha256="0" * 64, pages=[page], words=[], shapes=[], marks=[])
    assert page.images == []
    assert facts.images == []


def test_D2_extracts_cover_image_size_box_and_resolution(tmp_path):
    _image_interface()
    assert pdf_module is not None and hasattr(pdf_module, "PdfPlumberFacts")
    assert marks is not None and hasattr(marks, "ElementMark")
    render = _render_image(tmp_path)
    pages = pdf_module.PdfPlumberFacts().extract(render.pdf)
    assert len(pages) == 1 and pages[0].page == 1
    assert len(pages[0].images) == 1
    image = pages[0].images[0]
    assert isinstance(image, models.ImageFact)
    assert (image.native_w, image.native_h) == (320, 240)
    image_marks = [m for m in render.facts.marks if isinstance(m, marks.ElementMark) and m.role == "image"]
    assert len(image_marks) == 1
    mark = image_marks[0]
    assert mark.h > 0
    expected_dpi = 72 * 240 / mark.h
    assert image.dpi_x == pytest.approx(expected_dpi, rel=0.01)
    assert image.dpi_y == pytest.approx(expected_dpi, rel=0.01)
    assert image.box.page == 1
    assert image.box.x1 - image.box.x0 == pytest.approx(320 * 72 / image.dpi_x)
    assert image.box.y1 - image.box.y0 == pytest.approx(240 * 72 / image.dpi_y)


def test_D3_layout_facts_places_rendered_image(tmp_path):
    _image_interface()
    assert pdf_module is not None and hasattr(pdf_module, "PdfPlumberFacts")
    render = _render_image(tmp_path)
    extracted = pdf_module.PdfPlumberFacts().extract(render.pdf)
    assert len(extracted[0].images) == 1
    assert len(render.facts.images) == 1
    image = render.facts.images[0]
    assert isinstance(image, layout.PlacedImage)
    assert (image.section_id, image.role) == ("image-text1", "image")
    assert (image.dpi_x, image.dpi_y) == (extracted[0].images[0].dpi_x, extracted[0].images[0].dpi_y)
    assert image.box == extracted[0].images[0].box


def test_D4_join_places_images_by_centre_and_falls_back_to_section():
    _image_interface()
    assert marks is not None and hasattr(layout, "join")

    def image(x0, y0, x1, y1):
        return models.ImageFact(
            box=models.FactBox(page=1, x0=x0, y0=y0, x1=x1, y1=y1),
            native_w=320,
            native_h=240,
            dpi_x=144.0,
            dpi_y=120.0,
        )

    images = [image(5, 5, 35, 35), image(100, 100, 120, 120)]
    page = models.PageFacts(page=1, width=960, height=540, words=[], shapes=[], images=images)
    annotations = [
        marks.SectionMark(kind="section", id="s1", edge="start", page=1, x=0, y=0),
        marks.ElementMark(kind="element", id="s1", role="outer", page=1, x=0, y=0, w=80, h=80),
        marks.ElementMark(kind="element", id="s1", role="image", page=1, x=10, y=10, w=20, h=20),
        marks.SectionMark(kind="section", id="s1", edge="end", page=1, x=0, y=200),
    ]
    facts = layout.join([page], annotations, "a" * 64)
    assert [(item.role, item.section_id) for item in facts.images] == [("image", "s1"), (None, "s1")]
    assert [item.box for item in facts.images] == [item.box for item in images]
    assert [(item.native_w, item.native_h, item.dpi_x, item.dpi_y) for item in facts.images] == [
        (320, 240, 144.0, 120.0),
        (320, 240, 144.0, 120.0),
    ]


def test_D5_clean_build_has_no_images(tmp_path, capsys):
    _image_interface()
    assert cli is not None and hasattr(cli, "main")
    assert compose is not None and hasattr(compose, "font_paths")
    source = tmp_path / "deck.md"
    source.write_text(SLIDES)
    out = tmp_path / "out"
    assert cli.main(["build", str(source), "--out", str(out)]) == 0
    capsys.readouterr()
    root = out / "render"
    facts = layout.layout_facts(out / "deck.pdf", root / "main.typ", root, font_paths=compose.font_paths(root))
    assert len(facts.pages) == 2
    assert [page.images for page in facts.pages] == [[], []]
    assert facts.images == []


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.yaml")), ids=lambda path: path.stem)
def test_D6_component_goldens_still_match(path):
    assert golden is not None and hasattr(golden, "facts_for") and hasattr(golden, "compare_facts")
    saved = json.loads((FIXTURES / f"{path.stem}.facts.json").read_text())
    assert golden.compare_facts(golden.facts_for(path.stem, FIXTURES), saved) == []
