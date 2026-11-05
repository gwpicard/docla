# Intent: Golden layout facts capture the size and position of fixture images.
import importlib
import importlib.util
import inspect
import json
from pathlib import Path

import pytest
from PIL import Image


def _subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name
        if not missing or not (missing == name or name.startswith(f"{missing}.") or missing.startswith(f"{name}.")):
            raise
        try:
            spec = importlib.util.find_spec(missing)
        except ModuleNotFoundError:
            spec = None
        if spec is not None:
            raise
        return None


swatch_module = _subject("docla.render.swatch")
golden = _subject("docla.testing.golden")
model = _subject("docla.model")
theme = _subject("docla.theme")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "components"


def test_D1_swatch_resolves_assets_and_keeps_default(tmp_path):
    assert swatch_module is not None and hasattr(swatch_module, "swatch")
    assert model is not None and hasattr(model, "Document") and hasattr(model, "Section")
    assert theme is not None and hasattr(theme, "neutral_theme")
    assert "assets" in inspect.signature(swatch_module.swatch).parameters, "swatch must accept assets"
    assets = tmp_path / "assets"
    assets.mkdir()
    Image.new("RGB", (1600, 900), "blue").save(assets / "picture.png")
    section = model.Section(id="picture", intent="full-image", image="picture.png")
    doc = model.Document(front={}, format="slides", sections=[section])
    resolved = swatch_module.swatch(doc, "picture", tmp_path / "resolved", theme.neutral_theme(), assets=[assets])
    content = json.loads((resolved.main.parent / "composition.json").read_text())["sections"][0]["content"]
    assert content["image"].startswith("/assets/")
    assert content["image"] != "/assets/"
    default = swatch_module.swatch(doc, "picture", tmp_path / "default", theme.neutral_theme())
    content = json.loads((default.main.parent / "composition.json").read_text())["sections"][0]["content"]
    assert content["image"] == ""


@pytest.mark.parametrize("name", ["image-with-text", "full-image"])
def test_D2_fixture_image_has_area(name):
    assert golden is not None and hasattr(golden, "facts_for")
    facts = golden.facts_for(name, FIXTURES)
    assert "image" in facts and facts["image"]["marks"]
    mark = facts["image"]["marks"][0]
    assert mark["y1"] - mark["y0"] > 100
    assert mark["x1"] - mark["x0"] > 100


@pytest.mark.parametrize("name", ["image-with-text", "full-image"])
def test_D3_committed_image_golden_has_height(name):
    facts = json.loads((FIXTURES / f"{name}.facts.json").read_text())
    assert "image" in facts and facts["image"]["marks"]
    mark = facts["image"]["marks"][0]
    assert mark["y1"] - mark["y0"] > 100


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.facts.json")), ids=lambda path: path.name)
def test_D4_all_fixture_goldens_match(path):
    assert golden is not None and hasattr(golden, "facts_for") and hasattr(golden, "compare_facts")
    name = path.name.removesuffix(".facts.json")
    expected = json.loads(path.read_text())
    assert golden.compare_facts(golden.facts_for(name, FIXTURES), expected) == []
