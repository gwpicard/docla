# Intent: slide components follow a contrasting theme for type, colour and safe area.
import importlib
import importlib.util
import shutil
from pathlib import Path

import pytest
import yaml
from PIL import Image


def _import(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name or ""
        if (missing == name or name.startswith(missing + ".")) and importlib.util.find_spec(missing) is None:
            return None
        raise


model = _import("docla.model")
components = _import("docla.render.components")
compose = _import("docla.render.compose")
typst = _import("docla.render.typst")
layout = _import("docla.facts.layout")
theme = _import("docla.theme")
engine = _import("docla.checks.engine")
catalogue = _import("docla.checks.catalogue")
kit = _import("docla.render.kit")
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/components"
ROLES = {"ink": "#14213D", "ink-soft": "#3A4A6B", "muted": "#5C6B8A", "surface": "#FFFDF7",
         "surface-alt": "#F1EAD8", "accent": "#B5462B", "hairline": "#D9CDB3",
         "on-dark": "#FFFDF7", "dark": "#14213D"}
CHART = {"sequence": ["#14213D", "#3A4A6B", "#7C8BA8", "#D9CDB3"],
         "categorical": ["#B5462B", "#2A7F62", "#C99A2E", "#5B4B8A", "#14213D", "#7C8BA8"]}
SCALE = {"title": {"family": "display", "size": 40, "weight": 600},
         "subtitle": {"family": "text", "size": 26}, "body": {"family": "text", "size": 22, "leading": 1.3},
         "caption": {"family": "text", "size": 20}, "figure": {"family": "display", "size": 56, "weight": 600},
         "label": {"family": "text", "size": 20}, "min_size": 20}


@pytest.fixture(scope="module")
def contrast(tmp_path_factory):
    for module, names in ((model, ("Document", "Section")), (components, ("all_manifests",)),
                          (compose, ("compose", "assemble", "font_paths")), (typst, ("compile_pdf",)),
                          (layout, ("layout_facts",)), (theme, ("load_theme", "neutral_theme")),
                          (engine, ("CheckContext", "run_checks")), (catalogue, ("all_rules",)),
                          (kit, ("read_tokens",))):
        assert module is not None, "public rendering, theme and checking modules must exist"
        for name in names:
            assert hasattr(module, name), f"{module.__name__}.{name} must exist"
    folder = tmp_path_factory.mktemp("contrast") / "theme"
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


@pytest.fixture(scope="module")
def slides(tmp_path_factory, contrast):
    root = tmp_path_factory.mktemp("contrast-slides")
    result = {}
    manifests = [m for m in components.all_manifests().values() if m.format == "slides" and m.fixture]
    assert manifests, "the slide catalogue must contain fixtures"
    for manifest in manifests:
        name = manifest.name
        section = model.Section.model_validate(yaml.safe_load((FIXTURES / Path(manifest.fixture).name).read_text()))
        doc = model.Document(front={"doctype": "pitch-deck", "title": "Deck", "theme": "neutral"},
                             format="slides", sections=[section])
        assets = []
        if name in ("image-with-text", "full-image"):
            folder = root / (name + "-assets")
            image = folder / section.image
            image.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1600, 900), (80, 120, 160)).save(image, format="PNG")
            assets = [folder]
        built = compose.compose(doc, assets=assets)
        assert [s.component for s in built.sections] == [name]
        dest = root / name
        main = compose.assemble(built, dest, theme=contrast)
        fonts = compose.font_paths(dest)
        pdf = dest / "slide.pdf"
        typst.compile_pdf(main, dest, pdf, fonts)
        facts = layout.layout_facts(pdf, main, dest, font_paths=fonts)
        result[name] = (doc, section, facts, kit.read_tokens(dest))
    return result


def test_D1_contrast_theme_tokens(contrast):
    neutral = theme.neutral_theme().tokens
    tokens = contrast.tokens
    assert tokens.colour.roles == ROLES and tokens.colour.roles != neutral.colour.roles
    assert tokens.colour.chart == CHART and tokens.colour.chart != neutral.colour.chart
    assert tokens.colour.usage == {"text": ["ink", "ink-soft", "muted", "on-dark", "accent"],
                                   "fill": ["surface", "surface-alt", "dark", "accent"],
                                   "stroke": ["hairline", "ink-soft", "accent"]}
    assert tokens.colour.usage == neutral.colour.usage
    assert tokens.colour.contrast_min == 4.5 == neutral.colour.contrast_min
    assert tokens.type.families["display"].model_dump() == {"name": "Inter", "files": ["Inter-Regular.ttf", "Inter-SemiBold.ttf"]}
    assert tokens.type.families["text"].model_dump() == {"name": "Source Serif 4", "files": ["SourceSerif4-Regular.ttf", "SourceSerif4-Semibold.ttf"]}
    assert tokens.type.families != neutral.type.families
    scale = tokens.type.scale["slides"]
    assert scale.min_size == 20 and scale.min_size != neutral.type.scale["slides"].min_size
    for name, expected in SCALE.items():
        if name != "min_size":
            role = scale.roles[name]
            assert all(getattr(role, key) == value for key, value in expected.items())
            assert role != neutral.type.scale["slides"].roles[name]
    assert tokens.pages["slides"].margin.model_dump() == dict.fromkeys(("top", "right", "bottom", "left"), 56.0)
    assert tokens.pages["slides"].margin != neutral.pages["slides"].margin
    assert tokens.spacing.unit == 5 and tokens.spacing.unit != neutral.spacing.unit


def test_D2_every_fixture_is_one_page_and_passes_rules(slides, contrast):
    for name, (doc, _, facts, tokens) in slides.items():
        assert [(p.width, p.height) for p in facts.pages] == [(960, 540)], name
        context = engine.CheckContext(doc=doc, facts=facts, tokens=tokens, theme=contrast)
        assert engine.run_checks(catalogue.all_rules(), context) == [], name


def test_D3_title_and_item_fonts(slides):
    titles = items = 0
    for name, (_, section, facts, _) in slides.items():
        if section.title:
            assert any(word.role == "title" for word in facts.words), name
        for word in facts.words:
            if word.role == "title":
                titles += 1
                assert "inter" in word.font.lower(), (name, word)
            if word.role == "item":
                items += 1
                assert "sourceserif4" in word.font.lower().replace(" ", ""), (name, word)
    assert titles > 0 and items > 0


def test_D4_all_rendered_colours_are_from_contrast(slides, contrast):
    allowed = set(ROLES.values()) | {c for colours in CHART.values() for c in colours}
    neutral = theme.neutral_theme().tokens.colour
    forbidden = (set(neutral.roles.values()) | {c for colours in neutral.chart.values() for c in colours}) - allowed
    seen = set()
    for name, (_, _, facts, _) in slides.items():
        for word in facts.words:
            assert word.colour is not None, (name, word)
        for colour in [w.colour for w in facts.words] + [c for s in facts.shapes for c in (s.fill, s.stroke)]:
            if colour is not None:
                colour = colour.upper()
                seen.add(colour)
                assert colour in allowed and colour not in forbidden, (name, colour)
    assert seen


def test_D5_words_and_element_marks_stay_in_safe_area(slides):
    for name, (_, _, facts, _) in slides.items():
        for word in facts.words:
            box = word.box
            assert 56 <= box.x0 <= box.x1 <= 904 and 56 <= box.y0 <= box.y1 <= 484, (name, word)
        for mark in facts.marks:
            if mark.kind != "element" or mark.role == "section":
                continue
            if mark.x <= 0 and mark.y <= 0 and mark.x + mark.w >= 960 and mark.y + mark.h >= 540:
                continue
            assert 56 <= mark.x <= mark.x + mark.w <= 904 and 56 <= mark.y <= mark.y + mark.h <= 484, (name, mark)
