# Intent: the chooser maps a section's intent and content features to a component per format, as data, and compose uses it.
import importlib
from pathlib import Path

import pytest

from docla.model import Document, Item, Section


def _optional(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if name != module_name and not name.startswith(module_name + "."):
            raise
        return None


chooser_module = _optional("docla.render.chooser")
compose_module = _optional("docla.render.compose")


def _require_interface() -> None:
    assert chooser_module is not None, "docla.render.chooser must exist"
    for name in ("load_chooser", "Chooser", "ChooserError"):
        assert hasattr(chooser_module, name), f"docla.render.chooser.{name} must exist"
    assert hasattr(chooser_module.Chooser, "choose"), "Chooser.choose must exist"


def _write(tmp_path: Path, slides_bullets: str, extra_slides: str = "") -> Path:
    path = tmp_path / "chooser.yaml"
    path.write_text(
        "version: 1\n"
        "intents:\n"
        "  bullets:\n"
        "    describes: A list of points.\n"
        "    slides:\n"
        f"{slides_bullets}"
        f"{extra_slides}"
    )
    return path


def _load(path: Path):
    from docla.render.components import load_manifests

    return chooser_module.load_chooser(path, load_manifests())


def _bullets(n: int, chars: int = 20) -> Section:
    return Section(id="s", intent="bullets", items=[Item(body="x" * chars) for _ in range(n)])


COUNT_THEN_DEFAULT = (
    "      - {when: {count: [1, 3]}, component: bullets}\n"
    "      - {component: statement}\n"
)


def test_D1_packaged_chooser_matches_m1_components():
    _require_interface()
    assert compose_module is not None
    chooser = chooser_module.load_chooser()
    sections = {
        "statement": Section(id="a", intent="statement", title="Claim"),
        "bullets": _bullets(3),
        "body": Section(id="c", intent="body", title="T", paragraphs=["p"]),
        "callout": Section(id="d", intent="callout", title="T", items=[Item(body="x" * 20)]),
    }
    expected = {
        ("slides", "statement"): "statement",
        ("slides", "bullets"): "bullets",
        ("doc", "body"): "body",
        ("doc", "callout"): "callout",
    }
    assert dict(compose_module.M1_COMPONENTS) == expected
    for (fmt, intent), component in expected.items():
        assert chooser.choose(sections[intent], fmt, 0, 1) == component


def test_D2_count_range_selects_first_matching_entry(tmp_path):
    _require_interface()
    chooser = _load(_write(tmp_path, COUNT_THEN_DEFAULT))
    assert chooser.choose(_bullets(2), "slides", 0, 1) == "bullets"
    assert chooser.choose(_bullets(5), "slides", 0, 1) == "statement"


def test_D3_is_first_matches_only_index_zero(tmp_path):
    _require_interface()
    chooser = _load(
        _write(
            tmp_path,
            "      - {when: {is_first: true}, component: statement}\n      - {component: bullets}\n",
        )
    )
    assert chooser.choose(_bullets(2), "slides", 0, 3) == "statement"
    assert chooser.choose(_bullets(2), "slides", 1, 3) == "bullets"


def test_D3_max_item_chars_excludes_longer_item(tmp_path):
    _require_interface()
    chooser = _load(
        _write(
            tmp_path,
            "      - {when: {max_item_chars: [0, 40]}, component: bullets}\n      - {component: statement}\n",
        )
    )
    assert chooser.choose(_bullets(1, chars=40), "slides", 0, 1) == "bullets"
    assert chooser.choose(_bullets(1, chars=41), "slides", 0, 1) == "statement"


def test_D4_default_entry_not_last_raises(tmp_path):
    _require_interface()
    path = _write(tmp_path, "      - {component: statement}\n      - {when: {count: [1, 3]}, component: bullets}\n")
    with pytest.raises(chooser_module.ChooserError) as info:
        _load(path)
    assert "bullets" in str(info.value) and "slides" in str(info.value)


def test_D4_unknown_when_key_raises(tmp_path):
    _require_interface()
    path = _write(tmp_path, "      - {when: {colour: red}, component: bullets}\n      - {component: statement}\n")
    with pytest.raises(chooser_module.ChooserError) as info:
        _load(path)
    assert "bullets" in str(info.value) and "slides" in str(info.value)


def test_D5_component_without_manifest_raises(tmp_path):
    _require_interface()
    path = _write(tmp_path, "      - {component: nope}\n")
    with pytest.raises(chooser_module.ChooserError) as info:
        _load(path)
    assert "bullets" in str(info.value) and "slides" in str(info.value)


def test_D5_component_of_other_format_raises(tmp_path):
    _require_interface()
    path = _write(tmp_path, "      - {component: body}\n")
    with pytest.raises(chooser_module.ChooserError) as info:
        _load(path)
    assert "bullets" in str(info.value) and "slides" in str(info.value)


def test_D6_compose_uses_chooser_for_bullets():
    _require_interface()
    assert compose_module is not None
    doc = Document(front={}, format="slides", sections=[_bullets(2)])
    comp = compose_module.compose(doc)
    assert [s.component for s in comp.sections] == ["bullets"]


def test_D6_compose_null_component_raises_prose_error(tmp_path):
    _require_interface()
    assert compose_module is not None
    chooser = _load(_write(tmp_path, "      - {component: null}\n"))
    doc = Document(front={}, format="slides", sections=[_bullets(2)])
    with pytest.raises(compose_module.ComposeError) as info:
        compose_module.compose(doc, chooser=chooser)
    assert "prose" in str(info.value)
