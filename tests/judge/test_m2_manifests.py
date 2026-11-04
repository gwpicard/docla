# Intent: every component has a validated manifest that load_manifests reads and reports on faithfully.
import re
import shutil
from pathlib import Path

import pytest
import yaml

try:
    from docla.render import components, kit
except ImportError as error:
    name = str(error.name)
    if name not in ("docla", "docla.render", "docla.render.components", "docla.render.kit") and not name.startswith(
        "docla.render.components."
    ):
        raise
    components = None
    kit = None

EXPECTED = {
    "statement": ("slides", ["statement"], {"title_words": (1, 14)}, ["title"]),
    "bullets": (
        "slides",
        ["bullets"],
        {"title_words": (1, 8), "items": (1, 6), "item_chars": (10, 140)},
        ["title", "body", "item"],
    ),
    "body": ("doc", ["body"], {"title_words": (1, 10), "paragraphs": (1, 40)}, ["heading", "source"]),
    "callout": (
        "doc",
        ["callout"],
        {"title_words": (1, 8), "items": (1, 6), "item_chars": (10, 160)},
        ["callout"],
    ),
}


def _api():
    assert components is not None, "docla.render.components must exist"
    for member in ("load_manifests", "ManifestError", "ComponentManifest"):
        assert hasattr(components, member), f"docla.render.components.{member} must exist"
    assert kit is not None and hasattr(kit, "components_dir"), "docla.render.kit.components_dir must exist"
    return components


def _copy(tmp_path: Path) -> Path:
    _api()
    target = tmp_path / "components"
    shutil.copytree(kit.components_dir(), target)
    return target


def _edit(folder: Path, stem: str, **changes) -> None:
    path = folder / f"{stem}.yaml"
    data = yaml.safe_load(path.read_text())
    data.update(changes)
    path.write_text(yaml.safe_dump(data))


def test_D1_load_manifests_returns_the_four_components():
    api = _api()
    manifests = api.load_manifests()
    assert sorted(manifests) == ["body", "bullets", "callout", "statement"]
    for stem, (fmt, intents, capacity, elements) in EXPECTED.items():
        manifest = manifests[stem]
        assert manifest.name == stem
        assert manifest.format == fmt
        assert list(manifest.intents) == intents
        assert {k: tuple(v) for k, v in manifest.capacity.items()} == capacity
        assert list(manifest.elements) == elements
        assert manifest.label.strip() != ""


def test_D1_load_manifests_reads_an_explicit_folder(tmp_path):
    api = _api()
    folder = _copy(tmp_path)
    _edit(folder, "statement", label="Big claim")
    assert api.load_manifests(folder)["statement"].label == "Big claim"


def test_D2_capacity_text_sorts_measures():
    api = _api()
    assert api.load_manifests()["bullets"].capacity_text() == "items 1 to 6; item_chars 10 to 140; title_words 1 to 8"


def test_D2_capacity_text_for_single_measure():
    api = _api()
    assert api.load_manifests()["statement"].capacity_text() == "title_words 1 to 14"


def test_D3_typ_without_yaml_names_the_component(tmp_path):
    api = _api()
    folder = _copy(tmp_path)
    (folder / "bullets.yaml").unlink()
    with pytest.raises(api.ManifestError, match="bullets"):
        api.load_manifests(folder)


def test_D3_yaml_without_typ_names_the_component(tmp_path):
    api = _api()
    folder = _copy(tmp_path)
    (folder / "callout.typ").unlink()
    with pytest.raises(api.ManifestError, match="callout"):
        api.load_manifests(folder)


def test_D3_name_differing_from_stem_names_the_file(tmp_path):
    api = _api()
    folder = _copy(tmp_path)
    _edit(folder, "body", name="prose")
    with pytest.raises(api.ManifestError, match="body"):
        api.load_manifests(folder)


def test_D3_manifest_error_is_a_value_error():
    api = _api()
    assert issubclass(api.ManifestError, ValueError)


@pytest.mark.parametrize(
    "changes",
    [
        {"format": "poster"},
        {"intents": []},
        {"elements": []},
        {"label": ""},
        {"capacity": {"items": [5, 2]}},
    ],
    ids=["format", "intents", "elements", "label", "range"],
)
def test_D4_invalid_manifest_names_the_file(tmp_path, changes):
    api = _api()
    folder = _copy(tmp_path)
    _edit(folder, "bullets", **changes)
    with pytest.raises(api.ManifestError, match="bullets"):
        api.load_manifests(folder)


def test_D4_valid_copy_still_loads(tmp_path):
    api = _api()
    folder = _copy(tmp_path)
    assert sorted(api.load_manifests(folder)) == ["body", "bullets", "callout", "statement"]


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_D5_every_element_role_appears_in_the_typ_file(stem):
    api = _api()
    manifest = api.load_manifests()[stem]
    source = (kit.components_dir() / f"{stem}.typ").read_text()
    assert manifest.elements
    for role in manifest.elements:
        pattern = rf'\b(?:el|el-full-width|fit-box)\(\s*"{re.escape(role)}"'
        assert re.search(pattern, source), f"{stem}.typ must emit role {role!r}"
