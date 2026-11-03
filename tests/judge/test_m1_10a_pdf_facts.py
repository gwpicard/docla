# Intent: PdfPlumberFacts extracts per-page size, words and shapes from a PDF behind the PdfFacts interface.
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _optional(module_name: str):
    import importlib

    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if name != "docla.facts" and not name.startswith("docla.facts."):
            raise
        return None


pdf_module = _optional("docla.facts.pdf")
models = _optional("docla.facts.models")
from docla.render.typst import compile_pdf  # noqa: E402

PAGE = '#set page(width: 960pt, height: 540pt, margin: 0pt)\n'


def _require_interface() -> None:
    assert pdf_module is not None, "docla.facts.pdf must exist"
    for name in ("PdfFacts", "PdfPlumberFacts", "to_hex"):
        assert hasattr(pdf_module, name), f"docla.facts.pdf.{name} must exist"
    assert models is not None, "docla.facts.models must exist"
    for name in ("FactBox", "Word", "Shape", "PageFacts"):
        assert hasattr(models, name), f"docla.facts.models.{name} must exist"


def _extract(tmp_path: Path, source: str):
    _require_interface()
    main = tmp_path / "main.typ"
    main.write_text(source)
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, tmp_path, pdf)
    return pdf_module.PdfPlumberFacts().extract(pdf)


def test_D1_two_pages_numbered_with_size(tmp_path):
    pages = _extract(tmp_path, PAGE + "First\n#pagebreak()\nSecond\n")
    assert [p.page for p in pages] == [1, 2]
    for p in pages:
        assert abs(p.width - 960) < 0.01
        assert abs(p.height - 540) < 0.01


def test_D2_words_with_font_size_colour_box_baseline(tmp_path):
    source = PAGE + '#place(top + left, dx: 100pt, dy: 50pt, text(size: 20pt, fill: rgb("#2f5d8a"))[Hello world])\n'
    (page,) = _extract(tmp_path, source)
    assert [w.text for w in page.words] == ["Hello", "world"]
    for w in page.words:
        assert abs(w.size - 20) <= 0.1
        assert w.colour == "#2F5D8A"
        assert w.font
        assert w.box.page == 1
    hello, world = page.words
    assert abs(hello.box.x0 - 100) <= 0.5
    assert world.box.x0 > hello.box.x1
    assert hello.baseline == world.baseline
    assert hello.box.y0 < hello.baseline < hello.box.y1
    assert world.box.y0 < world.baseline < world.box.y1


def test_D3_filled_rect_shape(tmp_path):
    source = PAGE + '#place(top + left, dx: 100pt, dy: 50pt, rect(width: 200pt, height: 40pt, fill: rgb("#ff0000")))\n'
    (page,) = _extract(tmp_path, source)
    rects = [s for s in page.shapes if s.kind == "rect"]
    assert len(rects) == 1
    shape = rects[0]
    assert shape.fill == "#FF0000"
    assert shape.stroke is None
    expected = (100, 50, 300, 90)
    actual = (shape.box.x0, shape.box.y0, shape.box.x1, shape.box.y1)
    for got, want in zip(actual, expected, strict=True):
        assert abs(got - want) <= 0.5


def test_D4_protocol_and_to_hex():
    _require_interface()
    assert isinstance(pdf_module.PdfPlumberFacts(), pdf_module.PdfFacts)
    assert pdf_module.to_hex((1.0, 0.0, 0.0)) == "#FF0000"
    assert pdf_module.to_hex((0.5,)) == "#808080"
    assert pdf_module.to_hex(None) is None


def test_D5_pdfplumber_runtime_dependency_and_licences_pass():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dependencies = project["project"]["dependencies"]
    assert any(d.lower().startswith("pdfplumber") for d in dependencies), "pdfplumber must be a runtime dependency"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "licence_report.py")], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0, result.stdout + result.stderr
