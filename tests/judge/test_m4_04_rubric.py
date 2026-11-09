# Intent: themes provide a validated visual rubric for pages and sheets.
import importlib.util
import shutil

import pytest
import yaml

from docla.theme import ThemeError, load_theme, neutral_theme

if importlib.util.find_spec("docla.theme.rubric") is None:
    rubric_module = None
else:
    try:
        import docla.theme.rubric as rubric_module
    except ImportError as error:
        if error.name != "docla.theme.rubric" and not str(error.name).startswith("docla.theme.rubric."):
            raise
        rubric_module = None


def _load(theme):
    assert rubric_module is not None and hasattr(rubric_module, "load_rubric"), "load_rubric must exist"
    return rubric_module.load_rubric(theme)


def _copy(tmp_path):
    root = tmp_path / "theme"
    shutil.copytree(neutral_theme().root, root)
    return root


def _item(**changes):
    item = {
        "id": "sem.example",
        "question": "Is the page clear?",
        "severity": "warning",
        "remedy": {"class": "redraft", "hint": "Clarify the page."},
    }
    item.update(changes)
    return item


def _write(root, data):
    path = root / "rubric" / "visual.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data), encoding="utf-8")


def test_D1_neutral_items_and_properties():
    rubric = _load(neutral_theme())
    ids = rubric.ids()
    assert ids[:4] == ["sem.focal-point", "sem.repetition", "sem.balance", "sem.reader-words"]
    assert "sem.brand-feel" not in ids
    assert all(item.question.strip() and item.remedy.hint.strip() and item.examples is None for item in rubric.items)
    items = [rubric.get(rubric_id) for rubric_id in ids[:4]]
    assert [item.severity for item in items] == ["warning", "warning", "warning", "warning"]
    assert [item.remedy.class_ for item in items] == ["restructure", "restructure", "restructure", "redraft"]
    assert [item.view for item in items] == ["page", "sheet", "sheet", "page"]
    assert items[0].question == (
        "Is there one element a reader would look at first, or do all elements have equal weight?"
    )
    assert items[0].applies.components == ["chart", "key-figures", "statement"]


def test_D2_neutral_applies_and_lookup():
    rubric = _load(neutral_theme())
    statement = {item.id for item in rubric.applies("slides", "statement", "statement")}
    assert {"sem.focal-point", "sem.reader-words"} <= statement
    assert statement.isdisjoint({"sem.repetition", "sem.balance"})
    for fmt, component in [("slides", "bullets"), ("doc", "body")]:
        ids = {item.id for item in rubric.applies(fmt, component, component)}
        assert "sem.reader-words" in ids and "sem.focal-point" not in ids
    slides = {item.id for item in rubric.applies("slides", view="sheet")}
    assert "sem.repetition" in slides
    assert slides.isdisjoint({"sem.balance", "sem.focal-point", "sem.reader-words"})
    docs = {item.id for item in rubric.applies("doc", view="sheet")}
    assert "sem.balance" in docs and "sem.repetition" not in docs
    assert rubric.get("sem.balance").applies.formats == ["doc"]
    with pytest.raises(KeyError):
        rubric.get("sem.unknown")


def test_D2_restrictions_and_order(tmp_path):
    root = _copy(tmp_path)
    _write(
        root,
        {
            "items": [
                _item(id="sem.first", applies={"formats": ["slides"], "components": ["chart"], "intents": ["compare"]}),
                _item(id="sem.any"),
                _item(id="sem.last", applies={"components": ["chart"]}),
            ]
        },
    )
    rubric = _load(load_theme(root))
    assert rubric.ids() == ["sem.first", "sem.any", "sem.last"]
    assert [item.id for item in rubric.applies("slides", "chart", "compare")] == ["sem.first", "sem.any", "sem.last"]
    assert [item.id for item in rubric.applies("slides", "chart")] == ["sem.any", "sem.last"]
    assert [item.id for item in rubric.applies("doc", "chart", "compare")] == ["sem.any", "sem.last"]
    assert [item.id for item in rubric.applies("slides")] == ["sem.any"]
    assert rubric.applies("slides", "chart", "compare", view="sheet") == []


@pytest.mark.parametrize(
    "data",
    [
        {"items": [_item(weight=2)]},
        {"items": [_item(applies={"pages": [1]})]},
        {"items": [_item(id="geo.focal")]},
        {"items": [_item(severity="fatal")]},
        {"items": [_item(), _item()]},
        {"items": [_item(examples={"pass": ["missing.png"]})]},
        {"items": [_item(remedy={"class": "invent", "hint": "Fix it."})]},
        {"items": [_item(examples={"fail": [], "extra": []})]},
        {"items": [_item()], "extra": True},
        "items: [",
    ],
)
def test_D3_invalid_rubric_reports_path(tmp_path, data):
    root = _copy(tmp_path)
    _write(root, data)
    with pytest.raises(ThemeError) as caught:
        _load(load_theme(root))
    assert str(caught.value).startswith("rubric/visual.yaml: ")


def test_D3_example_must_stay_under_theme_root(tmp_path):
    root = _copy(tmp_path)
    (tmp_path / "outside.png").write_bytes(b"outside")
    _write(root, {"items": [_item(examples={"pass": ["../outside.png"]})]})
    with pytest.raises(ThemeError) as caught:
        _load(load_theme(root))
    assert str(caught.value).startswith("rubric/visual.yaml: ")


def test_D4_missing_and_existing_examples_and_repeat_load(tmp_path):
    root = _copy(tmp_path)
    shutil.rmtree(root / "rubric", ignore_errors=True)
    empty = _load(load_theme(root))
    assert empty.items == []
    assert empty.applies("slides", "statement", "statement") == []
    crop = root / "crops" / "flat.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"example")
    _write(root, {"items": [_item(examples={"fail": ["crops/flat.png"]})]})
    loaded = _load(load_theme(root))
    assert loaded.ids() == ["sem.example"]
    assert loaded.get("sem.example").examples.fail == ["crops/flat.png"]
    assert loaded.get("sem.example").examples.pass_ == []
    first, second = _load(neutral_theme()), _load(neutral_theme())
    assert first == second
