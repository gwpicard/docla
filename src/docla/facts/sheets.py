"""Deterministic page sheets for visual review."""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from docla.facts.layout import LayoutFacts
from docla.render.marks import SectionMark
from docla.theme import neutral_theme

MAX_SIDE = 1568
_GAP = 16
_LABEL_HEIGHT = 24


def page_labels(facts: LayoutFacts) -> list[str]:
    """Describe each page and the sections starting on it."""
    return [
        " ".join(
            [str(page.page)]
            + [
                mark.id
                for mark in facts.marks
                if isinstance(mark, SectionMark) and mark.edge == "start" and mark.page == page.page
            ]
        )
        for page in facts.pages
    ]


def _sheet(pngs: list[Path], labels: list[str], out: Path, font: Path | None, spread: bool) -> Path:
    if not pngs or len(pngs) != len(labels):
        raise ValueError("Pages and labels must be non-empty and have equal lengths")

    with Image.open(pngs[0]) as first:
        width, height = first.size
    count = (len(pngs) + 2) // 2 if spread else len(pngs)
    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    slots = 2 if spread else 1
    scale = min(
        1.0,
        (MAX_SIDE - _GAP * (columns - 1)) / (columns * slots * width),
        (MAX_SIDE - _GAP * (rows - 1) - rows * _LABEL_HEIGHT) / (rows * height),
    )
    tile_width = max(1, int(width * scale))
    tile_height = max(1, int(height * scale))
    sheet = Image.new(
        "RGB",
        (columns * slots * tile_width + (columns - 1) * _GAP,
         rows * (tile_height + _LABEL_HEIGHT) + (rows - 1) * _GAP),
        "white",
    )
    label_font = ImageFont.truetype(font or neutral_theme().fonts_dir / "Inter-Regular.ttf", 14)
    for index, (path, label) in enumerate(zip(pngs, labels, strict=True)):
        slot = index + 1 if spread else index
        group, side = divmod(slot, slots)
        row, column = divmod(group, columns)
        x = column * (slots * tile_width + _GAP) + side * tile_width
        y = row * (tile_height + _LABEL_HEIGHT + _GAP)
        with Image.open(path) as source:
            image = source.convert("RGB")
            factor = min(tile_width / image.width, tile_height / image.height)
            size = (max(1, int(image.width * factor)), max(1, int(image.height * factor)))
            image = image.resize(size, Image.Resampling.LANCZOS)
            sheet.paste(image, (x + (tile_width - size[0]) // 2, y + (tile_height - size[1]) // 2))
        if label:
            strip = Image.new("RGB", (tile_width, _LABEL_HEIGHT), "white")
            mask = Image.new("1", strip.size)
            ImageDraw.Draw(mask).text((0, 2), label, font=label_font, fill=1)
            strip.paste("#1A1A1A", mask=mask)
            sheet.paste(strip, (x, y + tile_height))
    sheet.save(out, format="PNG")
    return out


def contact_sheet(pngs: list[Path], labels: list[str], out: Path, *, font: Path | None = None) -> Path:
    """Arrange pages in reading order."""
    return _sheet(pngs, labels, out, font, False)


def spread_sheet(pngs: list[Path], labels: list[str], out: Path, *, font: Path | None = None) -> Path:
    """Arrange facing pages, starting with page one on the right."""
    return _sheet(pngs, labels, out, font, True)
