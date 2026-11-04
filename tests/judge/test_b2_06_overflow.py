# Intent: overflowing frames clip content and mark their bottom edge while preserving fit diagnostics.
import importlib
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image


def _subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(str(error.name) + "."):
            raise
        return None


kit = _subject("docla.render.kit")
marks = _subject("docla.render.marks")
typst = _subject("docla.render.typst")
compose = _subject("docla.render.compose")
parser = _subject("docla.source.parser")
facts = _subject("docla.facts")
cli = _subject("docla.cli")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects" / "geo.text-fits"


def _render(side, tmp_path):
    assert compose is not None and hasattr(compose, "assemble") and hasattr(compose, "compose")
    assert parser is not None and hasattr(parser, "parse")
    assert typst is not None and hasattr(typst, "compile_pdf")
    assert facts is not None and hasattr(facts, "PdfiumRasteriser")
    doc, _ = parser.parse((FIXTURES / side / "doc.md").read_text())
    root = tmp_path / side
    main = compose.assemble(compose.compose(doc), root)
    pdf = tmp_path / (side + ".pdf")
    typst.compile_pdf(main, root, pdf)
    pages = facts.PdfiumRasteriser().render(pdf, tmp_path / (side + "-pages"), scale=2)
    assert len(pages) == 1
    with Image.open(pages[0]) as image:
        return image.convert("RGB")


@pytest.mark.parametrize("height,ok", [(30, True), (60, False)])
def test_D1_fit_mark_and_wrap_height(tmp_path, height, ok):
    assert kit is not None and hasattr(kit, "lib_dir")
    assert marks is not None and hasattr(marks, "read_marks")
    assert hasattr(marks, "FitMark") and hasattr(marks, "ElementMark")
    shutil.copytree(kit.lib_dir(), tmp_path / "lib")
    main = tmp_path / "main.typ"
    main.write_text(
        '#import "/lib/marks.typ": el, fit-box\n'
        '#set page(width: 960pt, height: 540pt, margin: 0pt)\n'
        f'#el("wrap", "s1", fit-box("body", "s1", 200pt, 40pt, rect(width: 200pt, height: {height}pt)))\n'
    )
    result = marks.read_marks(main, tmp_path)
    assert [type(mark) for mark in result] == [marks.ElementMark, marks.FitMark]
    wrap, fit = result
    assert (wrap.role, wrap.id, wrap.h) == ("wrap", "s1", 40)
    assert (fit.role, fit.id, fit.have, fit.need, fit.ok) == ("body", "s1", 40, height, ok)


def test_D2_overflow_does_not_draw_text_below_frame(tmp_path):
    image = _render("fail", tmp_path)
    assert image.size == (1920, 1080)
    below = image.crop((80, 1000, 1840, 1080))
    assert not any(max(pixel) < 100 for pixel in below.getdata())


def test_D3_bar_marks_overflow_only(tmp_path):
    overflow = _render("fail", tmp_path)
    fitting = _render("pass", tmp_path)
    # The packaged theme's accent is #2f5d8a; sample away from antialiased edges.
    for y in (995, 997, 999):
        for x in (100, 500, 1000, 1800):
            assert overflow.getpixel((x, y)) == (47, 93, 138)
            assert fitting.getpixel((x, y)) != (47, 93, 138)


def test_D4_check_retains_overflow_and_item_lines(tmp_path, capsys):
    assert cli is not None and hasattr(cli, "main")
    out = tmp_path / "out"
    try:
        code = cli.main(["check", str(FIXTURES / "fail" / "doc.md"), "--out", str(out)])
    except SystemExit as error:
        code = error.code
    printed = capsys.readouterr().out
    assert code == 1
    assert any(line.startswith("error geo.text-fits ") for line in printed.splitlines())
    findings = json.loads((out / "doc.findings.json").read_text())
    fit = [finding for finding in findings if finding["rule_id"] == "geo.text-fits"]
    assert len(fit) == 1
    items = fit[0]["measured"]["items"]
    assert [item["n"] for item in items] == [0, 1, 2, 3, 4, 5, 6, 7, 8]
    assert items[0]["lines"] == 1
