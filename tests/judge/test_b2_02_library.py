# Intent: later components live in a separate library that joins the packaged components on demand.
import importlib
from pathlib import Path

import pytest


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not str(error.name).startswith(name + "."):
            raise
        return None


components = _optional("docla.render.components")
kit = _optional("docla.render.kit")
compose = _optional("docla.render.compose")
chooser = _optional("docla.render.chooser")
model = _optional("docla.model")


def _require():
    assert components is not None, "docla.render.components must exist"
    for name in ("load_manifests", "all_manifests", "ComponentManifest", "ManifestError"):
        assert hasattr(components, name), f"docla.render.components.{name} must exist"


def _library(folder: Path, name: str = "spark") -> Path:
    folder.mkdir()
    (folder / f"{name}.typ").write_text(f"#let {name}(sec) = [Library component]\n")
    (folder / f"{name}.yaml").write_text(
        f"name: {name}\nformat: slides\nlabel: Library component\n"
        "intents: [spark]\ncapacity: {title_words: [1, 10]}\nelements: [title]\n"
    )
    return folder


def _point_library(monkeypatch, folder):
    assert kit is not None and components is not None
    assert hasattr(kit, "library_dir") or hasattr(components, "library_dir"), "library_dir must exist"
    for module in (kit, components, compose, chooser):
        if module is not None and hasattr(module, "library_dir"):
            monkeypatch.setattr(module, "library_dir", lambda: folder)


def test_D1_default_manifests_stay_at_four():
    assert components is not None and hasattr(components, "load_manifests")
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_merge_and_manifest_fields(tmp_path):
    _require()
    folder = _library(tmp_path / "library")
    manifests = components.all_manifests(folder)
    assert sorted(manifests) == ["body", "bullets", "callout", "spark", "statement"]
    assert isinstance(manifests["spark"], components.ComponentManifest)
    assert manifests["spark"].fixture is None
    assert manifests["spark"].variants == []
    data = manifests["spark"].model_dump() | {
        "fixture": "tests/fixtures/components/spark.yaml", "variants": ["wide", "compact"]
    }
    manifest = components.ComponentManifest(**data)
    assert manifest.fixture == "tests/fixtures/components/spark.yaml"
    assert manifest.variants == ["wide", "compact"]
    assert sorted(components.all_manifests(tmp_path / "missing")) == ["body", "bullets", "callout", "statement"]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert sorted(components.all_manifests(empty)) == ["body", "bullets", "callout", "statement"]


def test_D3_duplicate_component_is_named(tmp_path):
    _require()
    folder = _library(tmp_path / "library", "statement")
    with pytest.raises(components.ManifestError, match="statement"):
        components.all_manifests(folder)


def test_D4_assemble_copies_library_and_packaged_components(tmp_path, monkeypatch):
    _require()
    assert kit is not None and compose is not None
    library_dir = getattr(components, "library_dir", None) or getattr(kit, "library_dir", None)
    assert callable(library_dir), "library_dir must exist"
    assert library_dir().is_dir()
    folder = _library(tmp_path / "library")
    assert "spark" in components.all_manifests(folder)
    _point_library(monkeypatch, folder)
    assert all(hasattr(compose, name) for name in ("assemble", "Composition", "ComposedSection"))
    comp = compose.Composition(format="slides", sections=[
        compose.ComposedSection(id="s", component="spark", props={"id": "s"}),
        compose.ComposedSection(id="t", component="statement", props={"id": "t"}),
    ])
    dest = tmp_path / "render"
    main = compose.assemble(comp, dest)
    assert main == dest / "main.typ"
    assert (dest / "components" / "spark.typ").read_text() == "#let spark(sec) = [Library component]\n"
    assert (dest / "components" / "statement.typ").read_text() == (kit.components_dir() / "statement.typ").read_text()
    assert '#import "/components/spark.typ": spark' in main.read_text()


def test_D5_default_chooser_accepts_library_and_rejects_unknown(tmp_path, monkeypatch):
    _require()
    assert chooser is not None and model is not None
    assert hasattr(chooser, "load_chooser") and hasattr(chooser, "ChooserError")
    assert hasattr(model, "Section")
    _point_library(monkeypatch, _library(tmp_path / "library"))
    path = tmp_path / "chooser.yaml"
    path.write_text("version: 1\nintents:\n  spark:\n    describes: A spark.\n    slides:\n      - {component: spark}\n")
    selected = chooser.load_chooser(path)
    assert selected.choose(model.Section(id="s", intent="spark"), "slides", 0, 1) == "spark"
    path.write_text("version: 1\nintents:\n  spark:\n    describes: A spark.\n    slides:\n      - {component: unknown}\n")
    with pytest.raises(chooser.ChooserError, match="unknown"):
        chooser.load_chooser(path)
