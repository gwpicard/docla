from pathlib import Path
from typing import Protocol, runtime_checkable

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from PIL import Image, ImageDraw

OUTLINE_COLOUR = "#DC0000"
OUTLINE_WIDTH = 4
# crop reads a page at the scale it was rendered at, so render and crop share one default.
DEFAULT_SCALE = 2.0


@runtime_checkable
class Rasteriser(Protocol):
    def render(self, pdf: Path, out_dir: Path, scale: float = DEFAULT_SCALE) -> list[Path]: ...


class PdfiumRasteriser:
    def render(self, pdf: Path, out_dir: Path, scale: float = DEFAULT_SCALE) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        document = pdfium.PdfDocument(pdf)
        try:
            return [_render_page(page, index, out_dir, scale) for index, page in enumerate(document, start=1)]
        finally:
            document.close()


def _render_page(page: pdfium.PdfPage, number: int, out_dir: Path, scale: float) -> Path:
    path = out_dir / f"p{number:02d}.png"
    bitmap = page.render(scale=scale, fill_color=(255, 255, 255, 255))
    bitmap.to_pil().convert("RGB").save(path, format="PNG")
    return path


def _pixels(box: tuple[float, float, float, float], scale: float) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return round(x0 * scale), round(y0 * scale), round(x1 * scale), round(y1 * scale)


def _clamp(box: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    width, height = size
    return max(0, x0), max(0, y0), min(width, x1), min(height, y1)


def crop(
    png: Path,
    box: tuple[float, float, float, float],
    out: Path,
    scale: float = DEFAULT_SCALE,
    pad_pt: float = 12.0,
    outline: bool = True,
) -> Path:
    with Image.open(png) as source:
        image = source.convert("RGB")
    x0, y0, x1, y1 = _pixels(box, scale)
    if outline:
        ImageDraw.Draw(image).rectangle((x0, y0, x1 - 1, y1 - 1), outline=OUTLINE_COLOUR, width=OUTLINE_WIDTH)
    pad = round(pad_pt * scale)
    image.crop(_clamp((x0 - pad, y0 - pad, x1 + pad, y1 + pad), image.size)).save(out, format="PNG")
    return out
