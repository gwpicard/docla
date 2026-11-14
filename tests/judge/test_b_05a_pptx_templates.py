# Intent: Read PowerPoint templates as traceable structural brand facts.
import hashlib
import importlib
import importlib.util
import io
import tomllib
import zipfile
from xml.etree import ElementTree
from pathlib import Path

import pytest
from PIL import Image

from docla import cli
from docla.brand.git import run_git
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


def _interface(*names):
    assert templates is not None, "docla.brand.templates must exist"
    for name in names:
        assert hasattr(templates, name), f"templates.{name} must exist"
    return templates


def _rewrite(data, changes):
    result = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(result, "w") as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename in changes:
                for old, new in changes[item.filename]:
                    assert old in content
                    content = content.replace(old, new, 1)
            target.writestr(item, content)
    return result.getvalue()


def _deck(path, hyperlink=False):
    from pptx import Presentation
    from pptx.util import Pt

    png = io.BytesIO()
    Image.new("RGB", (100, 50), (11, 95, 255)).save(png, format="PNG")
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[0])
    slide.shapes.title.text = "Quarterly review"
    if hyperlink:
        slide.shapes.title.click_action.hyperlink.address = "http://example.com"
    slide.shapes.add_picture(io.BytesIO(png.getvalue()), Pt(72), Pt(100), Pt(200), Pt(100))
    second = presentation.slides.add_slide(presentation.slide_layouts[1])
    second._element.set("show", "0")
    presentation.save(path)
    data = path.read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, "w") as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "ppt/theme/theme1.xml":
                theme = ElementTree.fromstring(content)
                ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
                accent = theme.find(".//a:clrScheme/a:accent1/a:srgbClr", ns)
                major = theme.find(".//a:majorFont/a:latin", ns)
                assert accent is not None and major is not None
                accent.set("val", "0B5FFF")
                major.set("typeface", "Inter")
                content = ElementTree.tostring(theme, encoding="utf-8", xml_declaration=True)
            target.writestr(item, content)
    path.write_bytes(output.getvalue())
    return png.getvalue(), [layout.name for layout in presentation.slide_layouts]


def test_D1_theme_and_page(tmp_path):
    subject = _interface("read_pptx")
    path = tmp_path / "deck.pptx"
    _deck(path)
    facts = subject.read_pptx(path, "materials/templates/deck.pptx")
    assert (facts.kind, facts.format, facts.page_model.width, facts.page_model.height) == ("pptx", "slides", 720, 540)
    colours = {colour.role: colour.hex for colour in facts.colours}
    assert {key: colours[key] for key in ("dk1", "dk2", "accent1", "accent2")} == {
        "dk1": "#000000", "dk2": "#1F497D", "accent1": "#0B5FFF", "accent2": "#C0504D"
    }
    accent = next(colour for colour in facts.colours if colour.role == "accent1")
    assert "theme" in accent.where and "accent1" in accent.where
    assert {font.role: font.family for font in facts.fonts} == {"major": "Inter", "minor": "Calibri"}


def test_D2_styles_and_layouts(tmp_path):
    subject = _interface("read_pptx")
    path = tmp_path / "deck.pptx"
    _, names = _deck(path)
    facts = subject.read_pptx(path, "materials/templates/deck.pptx")
    styles = {style.name: style for style in facts.styles}
    assert (styles["title"].kind, styles["title"].size, styles["title"].font, styles["title"].theme_colour) == (
        "text-level", 44, "Inter", "tx1"
    )
    assert (styles["body.1"].kind, styles["body.1"].size, styles["body.1"].font) == ("text-level", 32, "Calibri")
    assert [layout.name for layout in facts.layouts] == names
    assert "Title Slide" in names and "Title and Content" in names
    layout = next(layout for layout in facts.layouts if layout.name == "Title and Content")
    title = next(item for item in layout.placeholders if item.idx == 0)
    assert title.type == "title" and title.box is not None
    assert title.box.x0 == pytest.approx(36, abs=0.01)
    assert title.box.x1 == pytest.approx(684, abs=0.01)
    assert any(item.idx == 1 for item in layout.placeholders)


def test_D3_slide_shapes_and_media(tmp_path):
    subject = _interface("read_pptx")
    path = tmp_path / "deck.pptx"
    png, _ = _deck(path)
    facts = subject.read_pptx(path, "materials/templates/deck.pptx")
    assert len(facts.slides) == 2
    first, second = facts.slides
    assert (first.number, first.layout, first.hidden) == (1, "Title Slide", False)
    assert any(shape.text == "Quarterly review" for shape in first.shapes)
    picture = next(shape for shape in first.shapes if shape.kind == "picture")
    assert picture.box is not None
    assert (picture.box.x0, picture.box.y0, picture.box.x1, picture.box.y1) == pytest.approx((72, 100, 272, 200), abs=0.5)
    assert second.number == 2 and second.hidden is True
    assert "slide 2 is hidden" in facts.warnings
    assert len(facts.media) == 1
    assert facts.media[0].part.endswith(".png")
    assert facts.media[0].sha256 == hashlib.sha256(png).hexdigest()


def _brand(tmp_path):
    assert intake is not None and hasattr(intake, "take_in"), "docla.brand.intake.take_in must exist"
    root = tmp_path / ".brand"
    brand = init_brand("acme", root)
    folder = brand / "materials/templates"
    pptx = folder / "deck.pptx"
    _deck(pptx)
    potx = folder / "deck.potx"
    potx.write_bytes(_rewrite(pptx.read_bytes(), {"[Content_Types].xml": [
        (b'presentationml.presentation.main+xml', b'presentationml.template.main+xml')
    ]}))
    with zipfile.ZipFile(folder / "fake.pptx", "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
    intake.take_in(brand)
    return root, brand, potx


def test_D4_report_potx_unread_and_determinism(tmp_path):
    subject = _interface("read_templates", "TemplateReport")
    _, brand, potx = _brand(tmp_path)
    original = potx.read_bytes()
    report = subject.read_templates(brand)
    output = brand / "theme/ingest/templates.json"
    first = output.read_bytes()
    assert first.endswith(b"\n")
    assert subject.TemplateReport.model_validate_json(first) == report
    assert [item.source for item in report.templates] == ["materials/templates/deck.potx", "materials/templates/deck.pptx"]
    a, b = report.templates
    assert (a.colours, a.fonts, a.layouts) == (b.colours, b.fonts, b.layouts)
    assert potx.read_bytes() == original
    assert any(item.file == "materials/templates/fake.pptx" and item.reason for item in report.unread)
    subject.read_templates(brand)
    assert output.read_bytes() == first


def test_D4_zip_errors_and_external_links(tmp_path):
    subject = _interface("check_zip", "TemplateError")
    bad = tmp_path / "bad.pptx"
    bad.write_bytes(b"not a zip")
    with pytest.raises(subject.TemplateError):
        subject.check_zip(bad)
    path = tmp_path / "links.pptx"
    _deck(path, hyperlink=True)
    assert any("http://example.com" in warning for warning in subject.check_zip(path))


def test_D5_cli_and_dependency(tmp_path, capsys):
    _interface("read_templates")
    root, brand, _ = _brand(tmp_path)
    assert cli.main(["brand", "templates", "acme", "--root", str(root)]) == 0
    output = capsys.readouterr().out
    assert any("materials/templates/deck.pptx" in line and "slides" in line for line in output.splitlines())
    assert run_git(brand, "branch", "--show-current").strip() == "main"
    assert run_git(brand, "status", "--porcelain") == ""
    assert cli.main(["brand", "templates", "unknown", "--root", str(root)]) == 2
    project = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())
    assert any(dep.split(">=")[0].split("==")[0] == "python-pptx" for dep in project["project"]["dependencies"])
