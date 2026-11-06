# Intent: M1 components follow the theme and separate statement title and body.
import importlib
import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml


def _subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name or ""
        if not (missing == name or name.startswith(missing + ".") or missing.startswith(name + ".")):
            raise
        try:
            spec = importlib.util.find_spec(missing)
        except ModuleNotFoundError:
            spec = None
        if spec is not None:
            raise
        return None


model = _subject("docla.model")
components = _subject("docla.render.components")
compose = _subject("docla.render.compose")
typst = _subject("docla.render.typst")
layout = _subject("docla.facts.layout")
theme = _subject("docla.theme")
engine = _subject("docla.checks.engine")
catalogue = _subject("docla.checks.catalogue")
kit = _subject("docla.render.kit")
golden = _subject("docla.testing.golden")
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/components"
NAMES = ("statement", "bullets", "body", "callout")
ROLES = {
    "ink": "#14213D",
    "ink-soft": "#3A4A6B",
    "muted": "#5C6B8A",
    "surface": "#FFFDF7",
    "surface-alt": "#F1EAD8",
    "accent": "#B5462B",
    "hairline": "#D9CDB3",
    "on-dark": "#FFFDF7",
    "dark": "#14213D",
}
CHART = {
    "sequence": ["#14213D", "#3A4A6B", "#7C8BA8", "#D9CDB3"],
    "categorical": ["#B5462B", "#2A7F62", "#C99A2E", "#5B4B8A", "#14213D", "#7C8BA8"],
}
SCALE = {
    "title": {"family": "display", "size": 40, "weight": 600},
    "subtitle": {"family": "text", "size": 26},
    "body": {"family": "text", "size": 22, "leading": 1.3},
    "caption": {"family": "text", "size": 20},
    "figure": {"family": "display", "size": 56, "weight": 600},
    "label": {"family": "text", "size": 20},
    "min_size": 20,
}


def _require(module, *names):
    assert module is not None, "public docla module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"


def _fixture(name):
    path = FIXTURES / f"{name}.yaml"
    assert path.is_file(), f"missing fixture {path}"
    _require(model, "Section")
    return model.Section.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def contrast(tmp_path_factory):
    _require(theme, "load_theme")
    folder = tmp_path_factory.mktemp("m1-theme") / "theme"
    shutil.copytree(ROOT / "src/docla/themes/neutral", folder)
    path = folder / "tokens.yaml"
    tokens = yaml.safe_load(path.read_text(encoding="utf-8"))
    tokens["colour"]["roles"] = ROLES
    tokens["colour"]["chart"] = CHART
    tokens["type"]["families"] = {
        "display": {"name": "Inter", "files": ["Inter-Regular.ttf", "Inter-SemiBold.ttf"]},
        "text": {"name": "Source Serif 4", "files": ["SourceSerif4-Regular.ttf", "SourceSerif4-Semibold.ttf"]},
    }
    tokens["type"]["scale"]["slides"] = SCALE
    tokens["pages"]["slides"]["margin"] = dict.fromkeys(("top", "right", "bottom", "left"), "56pt")
    tokens["spacing"]["unit"] = 5
    path.write_text(yaml.safe_dump(tokens), encoding="utf-8")
    return theme.load_theme(folder)


def _render(name, selected_theme, dest, section=None):
    _require(model, "Document")
    _require(compose, "compose", "assemble", "font_paths")
    _require(typst, "compile_pdf")
    _require(layout, "layout_facts")
    _require(kit, "read_tokens")
    section = _fixture(name) if section is None else section
    fmt = "slides" if name in ("statement", "bullets") else "doc"
    doc = model.Document(
        front={"doctype": "pitch-deck" if fmt == "slides" else "report", "title": "Example", "theme": "neutral"},
        format=fmt,
        sections=[section],
    )
    built = compose.compose(doc)
    assert [s.component for s in built.sections] == [name]
    root = dest / "render"
    main = compose.assemble(built, root, theme=selected_theme)
    fonts = compose.font_paths(root)
    pdf = dest / "out.pdf"
    typst.compile_pdf(main, root, pdf, fonts)
    facts = layout.layout_facts(pdf, main, root, font_paths=fonts)
    return doc, section, facts, kit.read_tokens(root)


def _words_for(text, words):
    expected = text.split()
    assert expected, "fixture text must not be empty"
    actual = [word.text for word in words]
    for i in range(len(actual) - len(expected) + 1):
        if actual[i : i + len(expected)] == expected:
            return words[i : i + len(expected)]
    pytest.fail(f"fixture text {text!r} is not present as separate words: {actual!r}")


def _no_findings(rendered, selected_theme):
    _require(engine, "CheckContext", "run_checks")
    _require(catalogue, "all_rules")
    doc, _, facts, tokens = rendered
    context = engine.CheckContext(doc=doc, facts=facts, tokens=tokens, theme=selected_theme)
    assert engine.run_checks(catalogue.all_rules(), context) == []


def test_D1_statement_body_follows_title(tmp_path):
    _require(theme, "neutral_theme")
    _, section, facts, _ = _render("statement", theme.neutral_theme(), tmp_path)
    title = _words_for(section.title, facts.words)
    assert section.items and all(item.body for item in section.items)
    for item in section.items:
        body = _words_for(item.body, facts.words)
        assert min(word.box.y0 for word in body) > max(word.box.y1 for word in title)


@pytest.mark.parametrize("name", NAMES)
def test_D2_manifest_fixture_and_golden_match(name):
    _require(components, "all_manifests")
    _require(golden, "facts_for", "compare_facts")
    manifest = components.all_manifests()[name]
    assert manifest.fixture, f"{name} must name a fixture"
    fixture = ROOT / manifest.fixture
    assert fixture.is_file(), f"missing {fixture}"
    assert fixture.resolve() == (FIXTURES / f"{name}.yaml").resolve()
    path = FIXTURES / f"{name}.facts.json"
    assert path.is_file(), f"missing golden {path}"
    expected = json.loads(path.read_text(encoding="utf-8"))
    assert expected
    assert golden.compare_facts(golden.facts_for(name, FIXTURES), expected) == []


@pytest.mark.parametrize("name", ["statement", "bullets"])
def test_D3_contrast_slides_are_safe_and_use_theme_fonts(name, contrast, tmp_path):
    rendered = _render(name, contrast, tmp_path)
    _, section, facts, _ = rendered
    assert facts.words and section.items
    title = _words_for(section.title, facts.words)
    assert all("inter" in word.font.lower() for word in title)
    for item in section.items:
        item_words = _words_for(item.body, facts.words)
        assert all("sourceserif4" in word.font.lower().replace(" ", "") for word in item_words)
    if name == "bullets":
        # bullets keeps its fixed horizontal frame: tests/judge/test_m2_theme_in_builds.py D3 relies on it.
        return
    for word in facts.words:
        box = word.box
        assert 56 <= box.x0 <= box.x1 <= 904 and 56 <= box.y0 <= box.y1 <= 484, word
    for mark in facts.marks:
        if mark.kind == "element":
            assert 56 <= mark.x <= mark.x + mark.w <= 904 and 56 <= mark.y <= mark.y + mark.h <= 484, mark
    _no_findings(rendered, contrast)


@pytest.mark.parametrize("name", ["body", "callout"])
def test_D4_contrast_document_fonts_and_rules(name, contrast, tmp_path):
    rendered = _render(name, contrast, tmp_path)
    facts = rendered[2]
    assert facts.words
    for word in facts.words:
        assert any(font in word.font.lower().replace(" ", "") for font in ("inter", "sourceserif4")), word
    _no_findings(rendered, contrast)


@pytest.mark.parametrize("name", NAMES)
def test_D5_no_fixed_point_text_sizes_or_40pt_dx(name):
    path = ROOT / "src/docla/render/components" / f"{name}.typ"
    assert path.is_file()
    source = path.read_text(encoding="utf-8")
    assert re.search(r"\bsize\s*:\s*\d+(?:\.\d+)?\s*pt\b", source) is None
    if name != "bullets":
        assert re.search(r"\bdx\s*:\s*40(?:\.0+)?\s*pt\b", source) is None


def test_D6_neutral_statement_title_frame(tmp_path):
    _require(theme, "neutral_theme")
    inline = model.Section.model_validate(
        {"id": "s1", "intent": "statement", "title": "A clear direction",
         "items": [{"body": "Shared priorities make the work easier to coordinate."}]}
    )
    _, section, facts, _ = _render("statement", theme.neutral_theme(), tmp_path, section=inline)
    fits = [mark for mark in facts.marks if mark.kind == "fit" and mark.role == "title"]
    assert len(fits) == 1 and fits[0].have == 300
    assert facts.words, "statement must draw words"
    # The frame starts at y 120; a word box includes the font's ascender, so allow 2 pt above it.
    assert min(word.box.y0 for word in facts.words) >= 118
