# Intent: PdfiumRasteriser turns PDF pages into PNGs and crop cuts outlined evidence crops, behind a Rasteriser protocol.
import re
import tomllib
from pathlib import Path

try:
    from docla.facts import raster
except ImportError as error:
    if error.name != "docla.facts" and not str(error.name).startswith("docla.facts."):
        raise
    raster = None

from docla.render.typst import compile_pdf

ROOT = Path(__file__).resolve().parents[2]

RED = (255, 0, 0)
OUTLINE = (220, 0, 0)
WHITE = (255, 255, 255)

TWO_PAGES = """\
#set page(width: 960pt, height: 540pt, margin: 0pt)
#rect(width: 100pt, height: 100pt, fill: rgb("#0000ff"))
#pagebreak()
#rect(width: 50pt, height: 50pt, fill: rgb("#00ff00"))
"""

RED_RECT = """\
#set page(width: 400pt, height: 200pt, margin: 0pt)
#place(top + left, dx: 100pt, dy: 50pt, rect(width: 200pt, height: 40pt, fill: rgb("#ff0000")))
"""


def _require_interface() -> None:
    assert raster is not None, "docla.facts.raster must exist"
    for name in ("Rasteriser", "PdfiumRasteriser", "crop"):
        assert hasattr(raster, name), f"docla.facts.raster.{name} must exist"


def _pdf(tmp_path: Path, source: str) -> Path:
    main = tmp_path / "main.typ"
    main.write_text(source)
    pdf = tmp_path / "doc.pdf"
    compile_pdf(main, tmp_path, pdf)
    return pdf


def _render(tmp_path: Path, source: str, name: str = "pages") -> list[Path]:
    pdf = _pdf(tmp_path, source)
    return raster.PdfiumRasteriser().render(pdf, tmp_path / name)


def _open(path: Path):
    from PIL import Image

    image = Image.open(path)
    image.load()
    return image.convert("RGB")


def test_D1_two_pages_render_to_numbered_pngs(tmp_path):
    _require_interface()
    out_dir = tmp_path / "nested" / "pages"
    pdf = _pdf(tmp_path, TWO_PAGES)
    paths = raster.PdfiumRasteriser().render(pdf, out_dir, scale=2.0)
    assert [p.name for p in paths] == ["p01.png", "p02.png"]
    assert all(p.parent == out_dir and p.is_file() for p in paths)
    assert [_open(p).size for p in paths] == [(1920, 1080), (1920, 1080)]
    assert _open(paths[0]).getpixel((20, 20)) == (0, 0, 255)
    assert _open(paths[1]).getpixel((20, 20)) == (0, 255, 0)


def test_D1_default_scale_is_two(tmp_path):
    _require_interface()
    paths = _render(tmp_path, TWO_PAGES)
    assert _open(paths[0]).size == (1920, 1080)


def test_D2_rendering_twice_gives_identical_pixels(tmp_path):
    _require_interface()
    pdf = _pdf(tmp_path, TWO_PAGES)
    first = raster.PdfiumRasteriser().render(pdf, tmp_path / "a")
    second = raster.PdfiumRasteriser().render(pdf, tmp_path / "b")
    assert len(first) == len(second) == 2
    for one, two in zip(first, second, strict=True):
        assert _open(one).tobytes() == _open(two).tobytes()


def test_D3_filled_rectangle_is_red_and_background_is_white(tmp_path):
    _require_interface()
    (page,) = _render(tmp_path, RED_RECT)
    image = _open(page)
    assert image.size == (800, 400)
    assert image.getpixel((400, 140)) == RED
    assert image.getpixel((20, 20)) == WHITE


def test_D4_crop_has_padded_size_and_outline(tmp_path):
    _require_interface()
    (page,) = _render(tmp_path, RED_RECT)
    out = tmp_path / "crop.png"
    result = raster.crop(page, (100, 50, 300, 90), out)
    assert result == out and out.is_file()
    image = _open(out)
    assert image.size == (448, 128)
    # Box corner (200, 100) in page pixels; crop origin is (176, 76); two pixels inside is (26, 26).
    assert image.getpixel((26, 26)) == OUTLINE
    # Far from the outline, inside the box, the page's red shows through.
    assert image.getpixel((224, 64)) == RED
    # Padding outside the box is white page.
    assert image.getpixel((2, 2)) == WHITE


def test_D4_crop_without_outline_keeps_page_colour(tmp_path):
    _require_interface()
    (page,) = _render(tmp_path, RED_RECT)
    out = tmp_path / "plain.png"
    raster.crop(page, (100, 50, 300, 90), out, outline=False)
    image = _open(out)
    assert image.size == (448, 128)
    assert image.getpixel((26, 26)) == RED


def test_D4_crop_does_not_modify_the_source_png(tmp_path):
    _require_interface()
    (page,) = _render(tmp_path, RED_RECT)
    before = page.read_bytes()
    raster.crop(page, (100, 50, 300, 90), tmp_path / "crop.png")
    assert page.read_bytes() == before


def test_D5_crop_at_top_left_corner_is_clamped(tmp_path):
    _require_interface()
    (page,) = _render(tmp_path, RED_RECT)
    out = tmp_path / "corner.png"
    raster.crop(page, (0, 0, 100, 40), out)
    image = _open(out)
    # Unclamped it would be 248 x 128; clamped to the page it starts at (0, 0) and ends 12 pt past the box.
    assert image.size == (224, 104)


def test_D5_crop_at_bottom_right_corner_is_clamped(tmp_path):
    _require_interface()
    (page,) = _render(tmp_path, RED_RECT)
    out = tmp_path / "corner.png"
    raster.crop(page, (300, 160, 400, 200), out)
    assert _open(out).size == (224, 104)


def test_D6_pdfium_rasteriser_satisfies_the_protocol():
    _require_interface()
    assert isinstance(raster.PdfiumRasteriser(), raster.Rasteriser)
    assert not isinstance(object(), raster.Rasteriser)


def test_D6_runtime_dependencies_include_pypdfium2_and_pillow():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    names = {re.split(r"[<>=!~\[;\s]", dep, maxsplit=1)[0].lower() for dep in data["project"]["dependencies"]}
    assert "pypdfium2" in names
    assert "pillow" in names
