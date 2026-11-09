# Intent: Assemble deterministic, labelled contact and spread sheets for visual review.
import importlib
import importlib.util

import pytest
from PIL import Image, ImageChops

from docla import cli
from docla.facts.layout import LayoutFacts, layout_facts
from docla.facts.models import PageFacts
from docla.render.compose import font_paths

try:
    if importlib.util.find_spec("docla.facts.sheets") is None:
        sheets = None
    else:
        sheets = importlib.import_module("docla.facts.sheets")
except ImportError as error:
    if error.name != "docla.facts.sheets":
        raise
    sheets = None

COLOURS = [
    (220, 30, 30),
    (30, 180, 30),
    (30, 30, 220),
    (200, 150, 20),
    (180, 30, 180),
    (20, 170, 170),
    (120, 50, 20),
    (60, 100, 180),
    (100, 180, 60),
    (180, 60, 100),
    (70, 70, 70),
    (130, 130, 30),
]

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


def _interface(name):
    assert sheets is not None and hasattr(sheets, name), f"docla.facts.sheets.{name} must exist"
    return getattr(sheets, name)


def _pages(tmp_path, count, size):
    paths = []
    for index, colour in enumerate(COLOURS[:count]):
        path = tmp_path / f"page-{index}.png"
        Image.new("RGB", size, colour).save(path)
        paths.append(path)
    return paths


def _regions(image, count):
    image = image.convert("RGB")
    regions = []
    for colour in COLOURS[:count]:
        mask = Image.new("L", image.size)
        mask.putdata([255 if pixel == colour else 0 for pixel in image.getdata()])
        box = mask.getbbox()
        assert box is not None, f"page colour {colour} missing"
        regions.append(box)
    return regions


def test_D1_contact_sheet_order_size_and_no_upscaling(tmp_path):
    contact_sheet = _interface("contact_sheet")
    pages = _pages(tmp_path, 12, (1920, 1080))
    out = tmp_path / "contact.png"
    assert contact_sheet(pages, [str(i) for i in range(1, 13)], out) == out
    with Image.open(out) as image:
        assert image.format == "PNG"
        assert 0 < min(image.size) <= max(image.size) <= 1568
        regions = _regions(image, 12)
    centres = [((x0 + x1) / 2, (y0 + y1) / 2) for x0, y0, x1, y1 in regions]
    for i in range(12):
        assert centres[i][1] == centres[(i // 4) * 4][1]
        if i % 4:
            assert centres[i - 1][0] < centres[i][0]
        if i >= 4:
            assert centres[i - 4][1] < centres[i][1]
    single = _pages(tmp_path, 1, (400, 225))
    single_out = tmp_path / "single.png"
    assert contact_sheet(single, ["1"], single_out) == single_out
    with Image.open(single_out) as image:
        x0, y0, x1, y1 = _regions(image, 1)[0]
    assert (x1 - x0, y1 - y0) == (400, 225)


def test_D2_spreads_pair_pages_and_leave_first_left_slot_white(tmp_path):
    spread_sheet = _interface("spread_sheet")
    pages = _pages(tmp_path, 5, (595, 842))
    out = tmp_path / "spread.png"
    assert spread_sheet(pages, [str(i) for i in range(1, 6)], out) == out
    with Image.open(out) as source:
        assert source.format == "PNG"
        image = source.convert("RGB")
    assert max(image.size) <= 1568
    boxes = _regions(image, 5)
    for left, right in ((boxes[1], boxes[2]), (boxes[3], boxes[4])):
        assert left[1] == right[1] and left[3] == right[3]
        assert 0 <= right[0] - left[2] <= 1
    x0, y0, _, y1 = boxes[0]
    assert x0 > 0
    assert all(image.getpixel((x0 - 1, y)) == (255, 255, 255) for y in range(y0, y1))


@pytest.mark.parametrize("name", ["contact_sheet", "spread_sheet"])
def test_D3_labels_stay_under_pages_and_png_is_deterministic(tmp_path, name):
    make_sheet = _interface(name)
    pages = _pages(tmp_path, 2, (400, 225))
    labelled = tmp_path / "labelled.png"
    again = tmp_path / "again.png"
    blank = tmp_path / "blank.png"
    labels = ["1 aaaa1", "2 aaaa2"]
    assert make_sheet(pages, labels, labelled) == labelled
    assert make_sheet(pages, labels, again) == again
    assert labelled.read_bytes() == again.read_bytes()
    assert make_sheet(pages, ["", ""], blank) == blank
    with Image.open(labelled) as source:
        labelled_image = source.convert("RGB")
    with Image.open(blank) as source:
        blank_image = source.convert("RGB")
    assert labelled_image.size == blank_image.size
    regions = _regions(blank_image, 2)
    diff = ImageChops.difference(labelled_image, blank_image)
    assert diff.getbbox() is not None
    for y in range(diff.height):
        for x in range(diff.width):
            if diff.getpixel((x, y)) != (0, 0, 0):
                assert any(x0 <= x < x1 and y >= y1 for x0, _, x1, y1 in regions)


@pytest.mark.parametrize("name", ["contact_sheet", "spread_sheet"])
def test_D4_rejects_empty_pages_and_mismatched_labels(tmp_path, name):
    make_sheet = _interface(name)
    pages = _pages(tmp_path, 2, (20, 20))
    with pytest.raises(ValueError):
        make_sheet([], [], tmp_path / "empty.png")
    with pytest.raises(ValueError):
        make_sheet(pages, ["1"], tmp_path / "mismatch.png")


def test_D5_page_labels_from_built_slides_and_unmarked_page(tmp_path):
    page_labels = _interface("page_labels")
    source = tmp_path / "deck.md"
    source.write_text(SLIDES)
    out = tmp_path / "out"
    assert cli.main(["build", str(source), "--out", str(out)]) == 0
    render = out / "render"
    facts = layout_facts(out / "deck.pdf", render / "main.typ", render, font_paths=font_paths(render))
    assert page_labels(facts) == ["1 aaaa1", "2 aaaa2"]
    page = PageFacts(page=1, width=400, height=225, words=[], shapes=[])
    unmarked = LayoutFacts(pdf_sha256="", pages=[page], words=[], shapes=[], marks=[])
    assert page_labels(unmarked) == ["1"]
