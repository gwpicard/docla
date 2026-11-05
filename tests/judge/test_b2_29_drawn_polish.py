# Intent: four fixture slides draw complete, legible content across their available space.
import importlib
import importlib.util
import json
from itertools import combinations
from pathlib import Path

import pytest
import yaml


def _import(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name
        if missing is None or not (missing == name or name.startswith(missing + ".")):
            raise
        if importlib.util.find_spec(missing) is not None:
            raise
        return None


model = _import("docla.model")
compose = _import("docla.render.compose")
typst = _import("docla.render.typst")
layout = _import("docla.facts.layout")
theme = _import("docla.theme")
engine = _import("docla.checks.engine")
catalogue = _import("docla.checks.catalogue")
kit = _import("docla.render.kit")
golden = _import("docla.testing.golden")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "components"
NAMES = ("chart", "timeline", "process", "matrix")


@pytest.fixture(scope="module")
def slides(tmp_path_factory):
    interfaces = (
        (model, ("Document", "Section")), (compose, ("compose", "assemble", "font_paths")),
        (typst, ("compile_pdf",)), (layout, ("layout_facts",)), (theme, ("neutral_theme",)),
        (engine, ("CheckContext", "run_checks")), (catalogue, ("all_rules",)),
        (kit, ("read_tokens",)), (golden, ("facts_for", "compare_facts")),
    )
    for module, names in interfaces:
        assert module is not None, "public rendering and checking modules must exist"
        for name in names:
            assert hasattr(module, name), f"{module.__name__}.{name} must exist"
    root = tmp_path_factory.mktemp("drawn-polish")
    result = {}
    for name in NAMES:
        section = model.Section.model_validate(yaml.safe_load((FIXTURES / f"{name}.yaml").read_text()))
        doc = model.Document(front={"doctype": "pitch-deck", "title": "Deck", "theme": "neutral"},
                             format="slides", sections=[section])
        built = compose.compose(doc)
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


def _words(facts, section, *roles):
    return [w for w in facts.words if w.section_id == section.id and w.role in roles]


def _marks(facts, section, role):
    return [m for m in facts.marks if m.kind == "element" and m.id == section.id and m.role == role]


def _overlap(a, b):
    return a[0] == b[0] and a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]


def _word_box(word):
    b = word.box
    return (b.page, b.x0, b.y0, b.x1, b.y1)


def _mark_box(mark):
    return (mark.page, mark.x, mark.y, mark.x + mark.w, mark.y + mark.h)


def test_D1_chart_drawn_marks_and_labels(slides):
    _, section, facts, _, _ = slides["chart"]
    titles = _words(facts, section, "title")
    marks = _marks(facts, section, "chart-mark")
    labels = _words(facts, section, "chart-label")
    assert titles and len(marks) == 8 and labels
    assert max(m.y + m.h for m in marks) - min(m.y for m in marks) >= (500 - max(w.box.y1 for w in titles)) / 2
    assert all(not _overlap(_word_box(a), _word_box(b)) for a, b in combinations(labels, 2))
    assert all(not _overlap(_word_box(w), _mark_box(m)) for w in labels for m in marks)


def _contains_phrase(words, phrase):
    texts = [word.text for word in words]
    expected = phrase.split()
    return any(texts[i:i + len(expected)] == expected for i in range(len(texts) - len(expected) + 1))


def _item_phrases(facts, section):
    words = _words(facts, section, "item")
    groups = []
    for mark in _marks(facts, section, "item"):
        groups.append([w for w in words if w.box.page == mark.page
                       and mark.x <= (w.box.x0 + w.box.x1) / 2 <= mark.x + mark.w
                       and mark.y <= (w.box.y0 + w.box.y1) / 2 <= mark.y + mark.h])
    return groups


def test_D2_timeline_items_and_width(slides):
    _, section, facts, _, _ = slides["timeline"]
    words = _words(facts, section, "item", "date")
    dates = _words(facts, section, "date")
    assert sorted(w.text for w in dates) == ["2020", "2021", "2022", "2023"]
    for phrase in ("The project begins with a small team.", "The first product reaches its customers.",
                   "The team expands into new markets.", "A new service joins the portfolio."):
        assert any(_contains_phrase(group, phrase) for group in _item_phrases(facts, section)), phrase
    assert min(w.box.x0 for w in words) <= 50
    assert max(w.box.x1 for w in words) >= 800


def test_D3_process_items_heads_and_width(slides):
    _, section, facts, _, _ = slides["process"]
    steps = _words(facts, section, "step")
    items = _words(facts, section, "item")
    assert [w.text for w in steps] == ["Discover", "Plan", "Build", "Review"]
    assert all("→" not in w.text for w in steps)
    for phrase in ("Understand the needs of the team.", "Agree on the next steps together.",
                   "Turn the plan into a working service.", "Learn from the results and improve."):
        assert any(_contains_phrase(group, phrase) for group in _item_phrases(facts, section)), phrase
    assert min(w.box.x0 for w in steps + items) <= 50
    assert max(w.box.x1 for w in steps + items) >= 800


def test_D4_matrix_axis_labels_are_outside_and_distinct(slides):
    _, section, facts, _, _ = slides["matrix"]
    quadrants = _marks(facts, section, "quadrant")
    labels = _words(facts, section, "axis-label")
    words = _words(facts, section, "quadrant")
    assert len(quadrants) == 4 and labels and words
    bounds = (quadrants[0].page, min(m.x for m in quadrants), min(m.y for m in quadrants),
              max(m.x + m.w for m in quadrants), max(m.y + m.h for m in quadrants))
    assert all(not _overlap(_word_box(w), bounds) for w in labels)
    assert all((label.size, label.colour) != (word.size, word.colour) for label in labels for word in words)


@pytest.mark.parametrize("name", NAMES)
def test_D5_clean_checks_and_recorded_golden(slides, name):
    doc, _, facts, current_theme, tokens = slides[name]
    context = engine.CheckContext(doc=doc, facts=facts, tokens=tokens, theme=current_theme)
    assert engine.run_checks(catalogue.all_rules(), context) == []
    expected = json.loads((FIXTURES / f"{name}.facts.json").read_text(encoding="utf-8"))
    assert golden.compare_facts(golden.facts_for(name, FIXTURES), expected) == []
