from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pdfplumber
from pdfplumber.page import Page

from docla.facts.models import FactBox, ImageFact, PageFacts, Shape, ShapeKind, Word


@runtime_checkable
class PdfFacts(Protocol):
    def extract(self, pdf: Path) -> list[PageFacts]: ...


def _channel(value: float) -> int:
    return round(value * 255)


def _hex(red: int, green: int, blue: int) -> str:
    return f"#{red:02X}{green:02X}{blue:02X}"


def _cmyk(cyan: float, magenta: float, yellow: float, black: float) -> str:
    # Naive conversion; Typst emits sRGB by default, so CMYK is rare.
    red, green, blue = (_channel(1 - min(1.0, channel + black)) for channel in (cyan, magenta, yellow))
    return _hex(red, green, blue)


def _components(colour: Any) -> tuple[float, ...] | None:
    if isinstance(colour, int | float):
        return (float(colour),)
    if (
        isinstance(colour, Sequence)
        and not isinstance(colour, str)
        and all(isinstance(value, int | float) for value in colour)
    ):
        return tuple(float(value) for value in colour)
    return None


def to_hex(colour: Any) -> str | None:
    """Return a grey, RGB or CMYK colour as `#RRGGBB`, or None for anything else."""
    components = _components(colour)
    if components is None:
        return None
    if len(components) == 1:
        grey = _channel(components[0])
        return _hex(grey, grey, grey)
    if len(components) == 3:
        red, green, blue = (_channel(value) for value in components)
        return _hex(red, green, blue)
    if len(components) == 4:
        return _cmyk(*components)
    return None


def _box(page: int, item: dict[str, Any]) -> FactBox:
    return FactBox(
        page=page, x0=float(item["x0"]), y0=float(item["top"]), x1=float(item["x1"]), y1=float(item["bottom"])
    )


def _word(page: int, height: float, raw: dict[str, Any]) -> Word:
    first = raw["chars"][0]
    return Word(
        text=raw["text"],
        font=raw["fontname"],
        size=float(raw["size"]),
        colour=to_hex(first.get("non_stroking_color")),
        box=_box(page, raw),
        baseline=height - float(first["matrix"][5]),
    )


def _shape(page: int, kind: ShapeKind, raw: dict[str, Any]) -> Shape:
    fill = to_hex(raw.get("non_stroking_color")) if raw.get("fill") else None
    stroke = to_hex(raw.get("stroking_color")) if raw.get("stroke") else None
    return Shape(kind=kind, fill=fill, stroke=stroke, box=_box(page, raw))


def _image(page: int, raw: dict[str, Any]) -> ImageFact:
    box = _box(page, raw)
    native_w, native_h = raw["srcsize"]
    return ImageFact(
        box=box,
        native_w=native_w,
        native_h=native_h,
        dpi_x=native_w * 72 / (box.x1 - box.x0),
        dpi_y=native_h * 72 / (box.y1 - box.y0),
    )


def _page_facts(number: int, page: Page) -> PageFacts:
    height = float(page.height)
    raw_words = page.extract_words(extra_attrs=["fontname", "size"], return_chars=True)
    groups: list[tuple[ShapeKind, list[dict[str, Any]]]] = [
        ("rect", page.rects),
        ("line", page.lines),
        ("curve", page.curves),
    ]
    return PageFacts(
        page=number,
        width=float(page.width),
        height=height,
        words=[_word(number, height, raw) for raw in raw_words],
        shapes=[_shape(number, kind, raw) for kind, items in groups for raw in items],
        images=[_image(number, raw) for raw in page.images],
    )


class PdfPlumberFacts:
    """PdfFacts read with pdfplumber."""

    def extract(self, pdf: Path) -> list[PageFacts]:
        with pdfplumber.open(pdf) as document:
            return [_page_facts(number, page) for number, page in enumerate(document.pages, 1)]
