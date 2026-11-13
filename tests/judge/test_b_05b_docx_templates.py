# Intent: Read Word templates into effective, traceable template facts.
import importlib
import importlib.util
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

from docla import cli
from docla.brand.workspace import init_brand


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        if importlib.util.find_spec(name) is not None:
            raise
        return None


templates = _module("docla.brand.templates")
intake = _module("docla.brand.intake")


def _interfaces(*names):
    assert templates is not None, "docla.brand.templates must exist"
    for name in names:
        assert hasattr(templates, name), f"docla.brand.templates.{name} must exist"
    return templates


def _report(path):
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin = section.bottom_margin = Mm(20)
    section.left_margin = section.right_margin = Mm(25)
    document.styles["Normal"].font.name = "Source Serif 4"
    heading = document.styles["Heading 1"]
    heading.font.size = Pt(24)
    heading.font.color.rgb = RGBColor(0x0B, 0x5F, 0xFF)
    note = document.styles.add_style("Acme Note", WD_STYLE_TYPE.PARAGRAPH)
    note.base_style = document.styles["Normal"]
    note.font.italic = True
    section.header.paragraphs[0].text = "Acme confidential"
    cols = section._sectPr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        section._sectPr.append(cols)
    cols.set(qn("w:num"), "2")
    cols.set(qn("w:space"), "425")
    document.save(path)


def _dotx(source, target):
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as result:
        for entry in original.infolist():
            data = original.read(entry.filename)
            if entry.filename == "[Content_Types].xml":
                data = data.replace(b"wordprocessingml.document.main+xml", b"wordprocessingml.template.main+xml")
            result.writestr(entry, data)


def _brand(tmp_path, slides=False):
    assert intake is not None and hasattr(intake, "take_in"), "docla.brand.intake.take_in must exist"
    brand = init_brand("acme", tmp_path / ".brand")
    directory = brand / "materials/templates"
    _report(directory / "report.docx")
    _dotx(directory / "report.docx", directory / "report.dotx")
    if slides:
        from pptx import Presentation

        Presentation().save(directory / "deck.pptx")
    intake.take_in(brand)
    return brand


def test_D1_word_page_theme_and_running_text(tmp_path):
    module = _interfaces("read_docx")
    path = tmp_path / "report.docx"
    _report(path)
    facts = module.read_docx(path, "materials/templates/report.docx")
    assert (facts.kind, facts.format) == ("docx", "doc")
    assert facts.page_model.width == pytest.approx(595.28, abs=0.1)
    assert facts.page_model.height == pytest.approx(841.89, abs=0.1)
    assert facts.page_model.margins == pytest.approx([56.69, 70.87, 56.69, 70.87], abs=0.05)
    assert (facts.page_model.columns, facts.page_model.column_gap) == (2, 21.25)
    assert ("accent1", "#4F81BD") in [(item.role, item.hex) for item in facts.colours]
    assert {item.role: item.family for item in facts.fonts} == {"major": "Calibri", "minor": "Cambria"}
    assert any(item.kind == "header" and item.text == "Acme confidential" for item in facts.running)


def test_D2_effective_named_styles(tmp_path):
    module = _interfaces("read_docx")
    path = tmp_path / "report.docx"
    _report(path)
    facts = module.read_docx(path, "materials/templates/report.docx")
    styles = {style.name: style for style in facts.styles}
    normal = styles["Normal"]
    assert (normal.font, normal.size) == ("Source Serif 4", 11)
    assert normal.bold is None or normal.bold is False
    heading = styles["Heading 1"]
    assert (heading.font, heading.size, heading.bold) == ("Calibri", 24, True)
    assert (heading.colour, heading.theme_colour) == ("#0B5FFF", None)
    assert (heading.based_on, heading.where) == ("Normal", "word/styles.xml#Heading1")
    note = styles["Acme Note"]
    assert (note.font, note.size, note.italic) == ("Source Serif 4", 11, True)
    assert (styles["Heading 2"].font, styles["Heading 2"].theme_colour) == ("Calibri", "accent1")


def test_D3_style_inheritance_cycle():
    module = _interfaces("resolve_style")
    from docx.oxml import parse_xml

    styles = parse_xml(b'<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                       b'<w:style w:styleId="A"><w:basedOn w:val="B"/></w:style>'
                       b'<w:style w:styleId="B"><w:basedOn w:val="A"/><w:rPr><w:sz w:val="30"/>'
                       b'</w:rPr></w:style></w:styles>')
    assert module.resolve_style(styles, "A", {}) == {
        "font": None, "size": 15, "bold": None, "italic": None, "colour": None, "theme_colour": None,
    }


def test_D4_report_reads_dotx_and_preserves_pptx(tmp_path):
    module = _interfaces("read_templates", "read_pptx", "TemplateReport")
    brand = _brand(tmp_path, slides=True)
    dotx = brand / "materials/templates/report.dotx"
    before = dotx.read_bytes()
    result = module.read_templates(brand)
    report = module.TemplateReport.model_validate_json((brand / "theme/ingest/templates.json").read_text())
    assert result == report
    assert report.unread == []
    facts = {Path(item.source).name: item for item in report.templates}
    assert set(facts) == {"report.docx", "report.dotx", "deck.pptx"}
    docx, template = facts["report.docx"], facts["report.dotx"]
    assert (template.page_model, template.styles, template.colours) == (docx.page_model, docx.styles, docx.colours)
    assert dotx.read_bytes() == before
    deck = facts["deck.pptx"]
    baseline = module.read_pptx(brand / "materials/templates/deck.pptx", "materials/templates/deck.pptx")
    assert deck.format == "slides"
    assert (deck.colours, deck.fonts, deck.styles) == (baseline.colours, baseline.fonts, baseline.styles)
    assert ("accent1", "#4F81BD") in [(item.role, item.hex) for item in deck.colours]
    assert {item.role: item.family for item in deck.fonts} == {"major": "Calibri", "minor": "Calibri"}
    assert any(style.name == "title" and style.size == 44 for style in deck.styles)


def test_D5_cli_commits_and_declares_dependency(tmp_path, capsys):
    _interfaces("read_templates")
    brand = _brand(tmp_path)
    assert cli.main(["brand", "templates", "acme", "--root", str(tmp_path / ".brand")]) == 0
    output = capsys.readouterr().out
    assert any("materials/templates/report.docx" in line and "doc" in line for line in output.splitlines())
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=brand, text=True, capture_output=True, check=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=brand, text=True, capture_output=True, check=True)
    assert branch.stdout.strip() == "main"
    assert status.stdout == ""
    project = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())
    assert any(dep.split("[")[0].split(">=")[0].split("==")[0] == "python-docx" for dep in project["project"]["dependencies"])
