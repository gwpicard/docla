# Intent: Index readable PDF pages and reproducible visual evidence for brand setup.
import hashlib
import importlib
import importlib.util
from pathlib import Path

import pytest
from PIL import Image

from docla import cli
from docla.brand import workspace
from docla.brand.git import run_git
from docla.render.typst import compile_pdf


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        if importlib.util.find_spec(name) is not None:
            raise
        return None


pages = _module("docla.brand.pages")
intake = _module("docla.brand.intake")
FONTS = Path(__file__).resolve().parents[2] / "src/docla/themes/neutral/fonts"


def _interface():
    assert pages is not None, "docla.brand.pages must exist"
    for name in ("parse_pdfs", "load_pages", "PageIndex", "material_key"):
        assert hasattr(pages, name), f"docla.brand.pages.{name} must exist"
    return pages


def _brand(tmp_path):
    assert intake is not None and hasattr(intake, "take_in"), "docla.brand.intake.take_in must exist"
    brand = workspace.init_brand("acme", tmp_path / ".brand")
    Image.new("RGB", (200, 100), "blue").save(brand / "materials/guidelines/image.png")
    source = brand / "book.typ"
    source.write_text(
        "#set page(width: 960pt, height: 540pt, margin: 40pt)\n"
        '#set text(font: "Inter", size: 16pt)\n'
        "= Colour\nOur primary colour is Acme Blue.\n\n"
        '#rect(width: 80pt, height: 30pt, fill: rgb("#E4002B"))\n'
        '#image("materials/guidelines/image.png", width: 100pt)\n'
        "#pagebreak()\nSecond page.\n#pagebreak()\nThird page.\n"
    )
    compile_pdf(source, brand, brand / "materials/guidelines/book.pdf", [FONTS])
    source.write_text(
        '#set page(paper: "a4")\n#set text(font: "Source Serif 4")\nReport body.\n#pagebreak()\nSecond report page.\n'
    )
    compile_pdf(source, brand, brand / "materials/examples/report.pdf", [FONTS])
    source.unlink()
    (brand / "materials/examples/broken.pdf").write_bytes(b"not a pdf")
    intake.take_in(brand)
    return brand


def test_D1_page_order_geometry_roles_and_hashes(tmp_path):
    _interface()
    brand = _brand(tmp_path)
    index = _interface().parse_pdfs(brand)
    assert [(p.file, p.page) for p in index.pages] == [
        ("materials/guidelines/book.pdf", 1),
        ("materials/guidelines/book.pdf", 2),
        ("materials/guidelines/book.pdf", 3),
        ("materials/examples/report.pdf", 1),
        ("materials/examples/report.pdf", 2),
    ]
    for page in index.pages:
        assert page.sha256 == hashlib.sha256((brand / page.file).read_bytes()).hexdigest()
        if page.file == "materials/guidelines/book.pdf":
            assert (page.width, page.height, page.format, page.role) == (960, 540, "slides", "guidelines")
        else:
            assert page.width == pytest.approx(595.28, abs=0.1)
            assert page.height == pytest.approx(841.89, abs=0.1)
            assert page.format == "doc"
    assert all(item.file != "materials/examples/broken.pdf" for item in index.skipped)


def test_D2_text_fonts_colours_and_images(tmp_path):
    _interface()
    brand = _brand(tmp_path)
    index = _interface().parse_pdfs(brand)
    book = next(p for p in index.pages if p.file.endswith("book.pdf") and p.page == 1)
    report = next(p for p in index.pages if p.file.endswith("report.pdf") and p.page == 1)
    assert "Our primary colour is Acme Blue." in book.text
    assert {"Inter-SemiBold", "Inter-Regular"} <= {font.name for font in book.fonts}
    assert all("+" not in font.name for font in book.fonts)
    assert any((c.hex, c.use, c.count) == ("#E4002B", "fill", 1) for c in book.colours)
    assert len(book.images) == 1
    image = book.images[0]
    assert (image.native_w, image.native_h) == (200, 100)
    assert image.box.x1 - image.box.x0 == pytest.approx(100, abs=0.5)
    assert any(font.name.startswith("SourceSerif4") for font in report.fonts)


def test_D3_renders_and_deterministic_index(tmp_path):
    module = _interface()
    brand = _brand(tmp_path)
    index = module.parse_pdfs(brand)
    for page in index.pages:
        png = Path(page.png)
        assert not png.is_absolute()
        assert png.is_relative_to(Path("theme/ingest/work/pages"))
        assert (brand / png).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        with Image.open(brand / png) as image:
            assert image.width == pytest.approx(round(page.width * 110 / 72), abs=1)
    path = brand / "theme/ingest/pages.json"
    before = path.read_bytes()
    assert before.endswith(b"\n")
    assert module.PageIndex.model_validate_json(before) == index
    assert module.load_pages(brand) == index
    assert module.parse_pdfs(brand) == index
    assert path.read_bytes() == before
    assert module.material_key("materials/guidelines/Book v3.pdf") == "guidelines-book-v3-pdf"


def test_D4_gitignore_and_missing_manifest(tmp_path):
    module = _interface()
    brand = _brand(tmp_path)
    module.parse_pdfs(brand)
    module.parse_pdfs(brand)
    assert (brand / ".gitignore").read_text().splitlines().count("theme/ingest/work/") == 1
    empty = workspace.init_brand("empty", tmp_path / "other")
    with pytest.raises(workspace.BrandError, match="docla brand intake"):
        module.parse_pdfs(empty)


def test_D5_cli_records_index_in_clean_brand(tmp_path, capsys):
    _interface()
    brand = _brand(tmp_path)
    run_git(brand, "add", "-A")
    run_git(brand, "commit", "-m", "Add materials")
    root = brand.parent
    assert cli.main(["brand", "parse", "acme", "--root", str(root)]) == 0
    output = capsys.readouterr().out
    assert any("materials/guidelines/book.pdf" in line and "3 pages" in line for line in output.splitlines())
    assert run_git(brand, "branch", "--show-current").strip() == "main"
    assert run_git(brand, "status", "--porcelain") == ""
    assert run_git(brand, "ls-files", "theme/ingest/pages.json").strip() == "theme/ingest/pages.json"
    assert run_git(brand, "ls-files", "theme/ingest/work") == ""
    assert "Parse the brand's PDFs" in run_git(brand, "log", "--all", "-p")
    assert cli.main(["brand", "parse", "unknown", "--root", str(root)]) == 2
