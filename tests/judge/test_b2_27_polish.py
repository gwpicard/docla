# Intent: fixture slides use their body space and fix the image, chart and matrix layout defects.
import importlib
import importlib.util
from itertools import combinations
from pathlib import Path

import pytest
import yaml
from PIL import Image


def _import(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = str(error.name)
        if (missing == name or name.startswith(missing + ".")) and importlib.util.find_spec(missing) is None:
            return None
        raise


model = _import("docla.model")
compose = _import("docla.render.compose")
typst = _import("docla.render.typst")
layout = _import("docla.facts.layout")
theme = _import("docla.theme")
engine = _import("docla.checks.engine")
catalogue = _import("docla.checks.catalogue")
kit = _import("docla.render.kit")

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "components"
NINE = ("cover", "agenda", "two-column", "comparison", "key-figures", "table", "timeline", "people", "contact")
WIDE = ("two-column", "comparison", "key-figures", "table", "timeline", "people")
DEFECTS = ("full-image", "chart", "matrix")


@pytest.fixture(scope="module")
def slides(tmp_path_factory):
    interfaces = ((model, ("Document", "Section")), (compose, ("compose", "assemble", "font_paths")),
                  (typst, ("compile_pdf",)), (layout, ("layout_facts",)), (theme, ("neutral_theme",)),
                  (engine, ("CheckContext", "run_checks")), (catalogue, ("all_rules",)), (kit, ("read_tokens",)))
    for module, names in interfaces:
        assert module is not None, "public rendering and checking modules must exist"
        for name in names:
            assert hasattr(module, name), f"{module.__name__}.{name} must exist"
    root = tmp_path_factory.mktemp("polish")
    result = {}
    for name in NINE + DEFECTS:
        section = model.Section.model_validate(yaml.safe_load((FIXTURES / f"{name}.yaml").read_text()))
        doc = model.Document(front={"doctype": "pitch-deck", "title": "Deck", "theme": "neutral"},
                             format="slides", sections=[section])
        assets = []
        if name == "full-image":
            folder = root / "assets"
            image = folder / section.image
            image.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1600, 900), (80, 120, 160)).save(image, format="PNG")
            assets = [folder]
        built = compose.compose(doc, assets=assets)
        assert [s.component for s in built.sections] == [name]
        dest = root / name
        current_theme = theme.neutral_theme()
        main = compose.assemble(built, dest, theme=current_theme)
        fonts = compose.font_paths(dest)
        pdf = dest / "slide.pdf"
        typst.compile_pdf(main, dest, pdf, fonts)
        facts = layout.layout_facts(pdf, main, dest, font_paths=fonts)
        result[name] = (doc, section, facts, current_theme, kit.read_tokens(dest))
    return result


def _elements(facts, section, role):
    return [m for m in facts.marks if m.kind == "element" and m.id == section.id and m.role == role]


def _overlap(a, b):
    return a.x0 < b.x1 and b.x0 < a.x1 and a.y0 < b.y1 and b.y0 < a.y1


def _marks_overlap(a, b):
    return a.page == b.page and a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def _content(facts, section):
    return [item for item in facts.words + facts.shapes if item.section_id == section.id and item.role != "title"]


@pytest.mark.parametrize("name", NINE)
def test_D1_content_reaches_halfway_down_body(slides, name):
    _, section, facts, _, _ = slides[name]
    title = [w for w in facts.words if w.section_id == section.id and w.role == "title"]
    content = _content(facts, section)
    assert title and content
    assert max(item.box.y1 for item in content) >= (max(w.box.y1 for w in title) + 500) / 2


@pytest.mark.parametrize("name", WIDE)
def test_D2_content_uses_safe_area_width(slides, name):
    _, section, facts, _, _ = slides[name]
    content = _content(facts, section)
    assert content
    assert min(item.box.x0 for item in content) <= 50
    assert max(item.box.x1 for item in content) >= 800


def test_D3_table_header_and_rule(slides):
    _, section, facts, _, _ = slides["table"]
    headers = [w for w in facts.words if w.role == "table-header" and w.section_id == section.id]
    cells = [w for w in facts.words if w.role == "table-cell" and w.section_id == section.id]
    assert {w.text for w in headers} == {"Quarter", "Revenue", "Growth"}
    assert cells and all("bold" in w.font.lower() for w in headers)
    table_marks = _elements(facts, section, "figure")
    assert table_marks
    width = max(m.w for m in table_marks)
    header_bottom = max(w.box.y1 for w in headers)
    first_row_top = min(w.box.y0 for w in cells)
    assert any(s.box.y1 - s.box.y0 <= 2 and s.box.x1 - s.box.x0 >= 0.8 * width
               and header_bottom <= s.box.y0 <= s.box.y1 <= first_row_top
               and any((colour or "").lower() in {"#d5d8db", "#4a4f55"} for colour in (s.stroke, s.fill))
               for s in facts.shapes)


def test_D4_comparison_headings_and_divider(slides):
    _, section, facts, _, _ = slides["comparison"]
    words = [w for w in facts.words if w.section_id == section.id and w.role != "title"]
    heads = sorted((w for w in words if w.text == "Option"), key=lambda w: w.box.x0)
    assert len(heads) == 2
    assert all("bold" in w.font.lower() or (w.colour or "").lower() == "#2f5d8a" for w in heads)
    assert any(s.box.x1 - s.box.x0 <= 2 and s.box.y1 - s.box.y0 >= 100
               and heads[0].box.x1 < s.box.x0 <= s.box.x1 < heads[1].box.x0 for s in facts.shapes)


def _assert_clean(slide):
    doc, _, facts, current_theme, tokens = slide
    ctx = engine.CheckContext(doc=doc, facts=facts, tokens=tokens, theme=current_theme)
    assert engine.run_checks(catalogue.all_rules(), ctx) == []


@pytest.mark.parametrize("name", NINE)
def test_D5_nine_slides_pass_all_rules(slides, name):
    _assert_clean(slides[name])


def test_D6_full_image_and_caption_are_separate_and_safe(slides):
    _, section, facts, _, _ = slides["full-image"]
    images, captions = _elements(facts, section, "image"), _elements(facts, section, "caption")
    assert len(images) == len(captions) == 1
    image, caption = images[0], captions[0]
    assert image.w >= 400 and image.h >= 200
    for mark in (image, caption):
        assert 40 <= mark.x and mark.x + mark.w <= 920
        assert 40 <= mark.y and mark.y + mark.h <= 500
    assert not _marks_overlap(image, caption)


def test_D7_chart_figure_height_and_label_spacing(slides):
    _, section, facts, _, _ = slides["chart"]
    titles = [w for w in facts.words if w.role == "title" and w.section_id == section.id]
    figures = _elements(facts, section, "figure")
    labels = [w for w in facts.words if w.role == "chart-label" and w.section_id == section.id]
    assert titles and len(figures) == 1 and len(labels) >= 2
    assert figures[0].h >= (500 - max(w.box.y1 for w in titles)) / 2
    assert all(a.box.page != b.box.page or not _overlap(a.box, b.box) for a, b in combinations(labels, 2))


def test_D8_matrix_quadrants_boundaries_and_axis_labels(slides):
    _, section, facts, _, _ = slides["matrix"]
    quadrants = _elements(facts, section, "quadrant")
    labels = [w for w in facts.words if w.role == "axis-label" and w.section_id == section.id]
    assert len(quadrants) == 4 and labels
    assert all(m.w >= 300 and m.h >= 120 for m in quadrants)
    assert all(not _marks_overlap(a, b) for a, b in combinations(quadrants, 2))
    left = sorted(quadrants, key=lambda m: m.x)[:2]
    right = sorted(quadrants, key=lambda m: m.x)[2:]
    top = sorted(quadrants, key=lambda m: m.y)[:2]
    bottom = sorted(quadrants, key=lambda m: m.y)[2:]
    assert any(s.box.x1 - s.box.x0 <= 2 and s.box.y1 - s.box.y0 > 0
               and max(m.x + m.w for m in left) <= (s.box.x0 + s.box.x1) / 2 <= min(m.x for m in right)
               for s in facts.shapes)
    assert any(s.box.y1 - s.box.y0 <= 2 and s.box.x1 - s.box.x0 > 0
               and max(m.y + m.h for m in top) <= (s.box.y0 + s.box.y1) / 2 <= min(m.y for m in bottom)
               for s in facts.shapes)
    for word in labels:
        for mark in quadrants:
            assert word.box.page != mark.page or not (word.box.x0 < mark.x + mark.w and mark.x < word.box.x1
                                                       and word.box.y0 < mark.y + mark.h and mark.y < word.box.y1)


@pytest.mark.parametrize("name", DEFECTS)
def test_D9_fixed_slides_pass_all_rules(slides, name):
    _assert_clean(slides[name])
