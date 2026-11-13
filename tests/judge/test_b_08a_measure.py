# Measure example and guideline pages separately and retain their distributions.
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from docla.brand.git import run_git
from docla.brand.workspace import init_brand
from docla.facts.models import PageFacts
from docla.render.typst import compile_pdf

try:
    measure = importlib.import_module("docla.brand.measure")
except ImportError as error:
    if error.name != "docla.brand.measure":
        raise
    measure = None


def interface():
    assert measure is not None, "docla.brand.measure must exist"
    for name in ("PageRef", "Measurement", "measure_brand", "load_measurement"):
        assert hasattr(measure, name), f"docla.brand.measure.{name} must exist"
    return measure


def pdf(brand, path, source):
    source_path = brand / "input.typ"
    source_path.write_text(source)
    fonts = Path(__file__).resolve().parents[2] / "src/docla/themes/neutral/fonts"
    compile_pdf(source_path, brand, brand / path, [fonts])
    source_path.unlink()


def slides(titles, vertical, horizontal):
    pages = []
    for title in titles:
        pages.append(
            '#set text(font: "Source Serif 4", size: 36pt, weight: 600, fill: rgb("#101820"))\n'
            + title
            + '\n#v(14pt)\n#set text(font: "Inter", size: 20pt, fill: rgb("#101820"))\n'
            + "This is the first body line with enough words.\\\n"
            + "This is the second body line with enough words.\n"
            + '#place(bottom, rect(width: 100%, height: 4pt, fill: rgb("#0B5FFF")))'
        )
    return (
        f"#set page(width: 960pt, height: 540pt, margin: (top: {vertical}pt, "
        f"bottom: {vertical}pt, left: {horizontal}pt, right: {horizontal}pt))\n" + "\n#pagebreak()\n".join(pages)
    )


@pytest.fixture
def brand(tmp_path):
    if measure is None:
        return None
    from docla.brand.intake import take_in
    from docla.brand.pages import parse_pdfs

    brand = init_brand("acme", tmp_path / ".brand")
    pdf(brand, "materials/examples/deck-a.pdf", slides(["Sales grew in the north", "Costs held"], 40, 48))
    pdf(brand, "materials/examples/deck-b.pdf", slides(["Margins rose", "Next steps"], 40, 52))
    report = (
        '#set text(font: "Source Serif 4", size: 16pt)\nReport heading\n'
        "#v(10pt)\n#set text(size: 11pt)\n"
        "This report has enough body text to make the body size clear.\\\n"
        "Another line of report body text for this page.\n"
        '#place(bottom, rect(width: 100%, height: 4pt, fill: rgb("#0B5FFF")))'
    )
    pdf(
        brand,
        "materials/examples/report.pdf",
        '#set page(paper: "a4", margin: (top: 20mm, bottom: 20mm, left: 25mm, right: 25mm))\n'
        + report
        + "\n#pagebreak()\n"
        + report,
    )
    pdf(
        brand,
        "materials/guidelines/book.pdf",
        "#set page(width: 960pt, height: 540pt, margin: 60pt)\nColour\n#pagebreak()\n"
        + slides(["Specimen title"], 60, 60)
        + "\n#pagebreak()\n#set page(width: 600pt, height: 600pt, margin: 60pt)\nOther",
    )
    take_in(brand)
    parse_pdfs(brand)
    return brand


def measured(brand):
    m = interface()
    refs = [m.PageRef(file="materials/guidelines/book.pdf", page=n) for n in (2, 3)]
    return m.measure_brand(brand, layout_pages=refs)


def get_set(result, kind, fmt):
    matches = [s for s in result.sets if (s.kind, s.format) == (kind, fmt)]
    assert len(matches) == 1
    return matches[0]


def test_D1_slide_measurements(brand):
    interface()
    s = get_set(measured(brand), "examples", "slides")
    assert len(s.pages) == 4
    assert s.width.value == 960 and s.height.value == 540
    assert s.margin["left"].value == pytest.approx(50, abs=0.5)
    assert s.margin["left"].min == pytest.approx(48, abs=0.5)
    assert s.margin["left"].max == pytest.approx(52, abs=0.5)
    assert s.margin["left"].n == 4
    assert s.margin["right"].value == pytest.approx(50, abs=0.5)
    assert s.margin["bottom"].value == pytest.approx(40, abs=0.5)
    assert s.margin["top"].value == pytest.approx(40, abs=2)
    assert s.title_size.value == 36 and s.body_size.value == 20
    assert s.title_font.startswith("SourceSerif4") and s.body_font.startswith("Inter")
    assert s.text_colours[0].hex == "#101820"
    assert any(c.hex == "#0B5FFF" and c.count == 4 for c in s.fill_colours)
    assert [t.text for t in s.titles] == ["Sales grew in the north", "Costs held", "Margins rose", "Next steps"]


def test_D2_document_measurements_are_separate(brand):
    interface()
    result = measured(brand)
    doc = get_set(result, "examples", "doc")
    slide_set = get_set(result, "examples", "slides")
    assert [(p.file, p.page) for p in doc.pages] == [
        ("materials/examples/report.pdf", 1),
        ("materials/examples/report.pdf", 2),
    ]
    assert all(p.file != "materials/examples/report.pdf" for p in slide_set.pages)
    assert doc.width.value == pytest.approx(595.28, abs=0.1)
    assert doc.height.value == pytest.approx(841.89, abs=0.1)
    assert doc.margin["left"].value == pytest.approx(70.87, abs=0.5)
    assert doc.margin["bottom"].value == pytest.approx(56.69, abs=0.5)
    assert doc.body_size.value == 11 and doc.title_size.value == 16


def test_D3_layout_page_and_reduced_scale(brand):
    interface()
    result = measured(brand)
    layout = get_set(result, "layout-pages", "slides")
    assert [(p.file, p.page) for p in layout.pages] == [("materials/guidelines/book.pdf", 2)]
    assert layout.margin["left"].value == pytest.approx(60, abs=0.5)
    assert layout.margin["bottom"].value == pytest.approx(60, abs=0.5)
    assert any(
        p.file == "materials/guidelines/book.pdf" and p.page == 3 and "reduced scale" in p.reason
        for p in result.skipped
    )
    assert all((p.file, p.page) != ("materials/guidelines/book.pdf", 1) for s in result.sets for p in s.pages)
    assert all((p.file, p.page) != ("materials/guidelines/book.pdf", 1) for p in result.skipped)


def test_D4_persistence_and_empty_pages(brand):
    m = interface()
    result = measured(brand)
    path = brand / "theme/ingest/measure.json"
    saved = path.read_bytes()
    assert saved.endswith(b"\n")
    assert m.Measurement.model_validate_json(saved) == result == m.load_measurement(brand)
    assert measured(brand) == result and path.read_bytes() == saved

    class EmptyExtractor:
        def extract(self, path):
            from docla.facts.pdf import PdfPlumberFacts

            return [
                PageFacts(page=p.page, width=p.width, height=p.height, words=[], shapes=[], images=[])
                for p in PdfPlumberFacts().extract(path)
            ]

    refs = [m.PageRef(file="materials/guidelines/book.pdf", page=2)]
    empty = m.measure_brand(brand, layout_pages=refs, extractor=EmptyExtractor())
    assert empty.sets == []
    assert len(empty.skipped) == 7
    assert all(p.reason == "no content" for p in empty.skipped)


def test_D5_cli_measures_and_records_change(brand, capsys):
    interface()
    from docla.brand.pages import load_pages
    from docla.brand.segment import PageTopics, TopicFile, TopicMap

    from docla.cli import main

    entry = next(p for p in load_pages(brand).pages if p.file == "materials/guidelines/book.pdf")
    topics = TopicMap(
        files=[
            TopicFile(
                file=entry.file,
                sha256=entry.sha256,
                formats=["doc", "slides"],
                pages=[
                    PageTopics(page=1, topics=["colour"]),
                    PageTopics(page=2, topics=["grid-layout"]),
                    PageTopics(page=3, topics=["other"]),
                ],
                missing=[],
            )
        ]
    )
    (brand / "theme/ingest/topics.json").write_text(topics.model_dump_json(indent=2) + "\n")
    run_git(brand, "add", "-A")
    run_git(brand, "commit", "-m", "Prepare measurement")
    assert main(["brand", "measure", "acme", "--root", str(brand.parent)]) == 0
    assert any(
        "examples" in line and "slides" in line and "4 pages" in line for line in capsys.readouterr().out.splitlines()
    )
    assert run_git(brand, "branch", "--show-current").strip() == "main"
    assert run_git(brand, "status", "--porcelain") == ""
    records = []
    for path in brand.rglob("*.json"):
        if ".git" not in path.parts:
            try:
                records.append(json.loads(path.read_text()))
            except (ValueError, UnicodeDecodeError):
                pass
    assert any(isinstance(r, dict) and r.get("what") == "Measure the brand's pages" for r in records)
    assert main(["brand", "measure", "unknown", "--root", str(brand.parent)]) == 2
