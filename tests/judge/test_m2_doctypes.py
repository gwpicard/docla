# Intent: Doctypes load from YAML into validated models, with the packaged pitch-deck and report doctypes and clear errors for bad files.
import importlib
from pathlib import Path

import pytest


def _optional(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if name != "docla.doctypes" and not name.startswith("docla.doctypes."):
            raise
        return None


doctypes = _optional("docla.doctypes")


def _require_interface() -> None:
    assert doctypes is not None, "docla.doctypes must exist"
    for name in ("load_doctype", "load_doctypes", "DoctypeError", "Doctype", "OutlineEntry"):
        assert hasattr(doctypes, name), f"docla.doctypes.{name} must exist"


def _write(
    tmp_path: Path,
    stem: str,
    *,
    fmt: str = "slides",
    outline: str,
    length: str = "slides: [3, 20]",
    name: str | None = None,
) -> Path:
    text = (
        f"name: {name or stem}\n"
        f"format: {fmt}\n"
        "audience: Test readers\n"
        f"length: {{{length}}}\n"
        "questions:\n"
        "  - key: purpose\n"
        "    ask: What is this for?\n"
        "outline:\n"
        f"{outline}"
        "checks: []\n"
        "checklist:\n"
        "  - Is it clear?\n"
    )
    path = tmp_path / f"{stem}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_D1_packaged_doctypes_load():
    _require_interface()
    loaded = doctypes.load_doctypes()
    assert set(loaded) == {"pitch-deck", "report"}

    deck = loaded["pitch-deck"]
    assert deck.name == "pitch-deck"
    assert deck.format == "slides"
    assert tuple(deck.length["slides"]) == (3, 20)
    assert [e.section for e in deck.outline] == ["opener", "content", "ask"]
    assert [e.intent for e in deck.outline] == ["statement", "any", "statement"]
    assert [e.required for e in deck.outline][0::2] == [True, True]
    assert deck.outline[1].repeat == (1, 16)
    assert [q.key for q in deck.questions] == ["decision", "length"]
    assert len(deck.checklist) == 2

    report = loaded["report"]
    assert report.name == "report"
    assert report.format == "doc"
    assert tuple(report.length["pages"]) == (1, 40)
    assert [e.section for e in report.outline] == ["introduction", "content", "findings"]
    assert [e.intent for e in report.outline] == ["body", "any", "callout"]
    assert [e.required for e in report.outline][0::2] == [True, True]
    assert report.outline[1].repeat == (1, 30)
    assert [q.key for q in report.questions] == ["purpose", "reader"]
    assert len(report.checklist) == 2


def test_D1_load_doctype_reads_a_file(tmp_path):
    _require_interface()
    path = _write(
        tmp_path,
        "mini",
        outline="  - section: opener\n    intent: statement\n    required: true\n",
    )
    doctype = doctypes.load_doctype(path)
    assert doctype.name == "mini"
    assert doctype.format == "slides"
    assert doctype.audience == "Test readers"
    assert doctype.questions[0].key == "purpose"
    assert doctype.questions[0].ask == "What is this for?"
    assert doctype.checklist == ["Is it clear?"]
    assert doctype.outline[0].required is True
    assert doctype.outline[0].repeat is None
    assert doctype.outline[0].fill == "facts"


def test_D2_unknown_intent_names_intent_and_file(tmp_path):
    _require_interface()
    path = _write(tmp_path, "tl", outline="  - section: when\n    intent: timeline\n")
    with pytest.raises(doctypes.DoctypeError) as caught:
        doctypes.load_doctype(path)
    message = str(caught.value)
    assert "timeline" in message
    assert "tl.yaml" in message


def test_D2_intent_of_the_other_format_is_rejected(tmp_path):
    _require_interface()
    path = _write(
        tmp_path, "wrong", fmt="doc", length="pages: [1, 5]", outline="  - section: x\n    intent: statement\n"
    )
    with pytest.raises(doctypes.DoctypeError) as caught:
        doctypes.load_doctype(path)
    assert "statement" in str(caught.value)


def test_D2_any_intent_is_accepted(tmp_path):
    _require_interface()
    path = _write(tmp_path, "anyok", outline="  - section: stuff\n    intent: any\n")
    doctype = doctypes.load_doctype(path)
    assert doctype.outline[0].intent == "any"


def test_D3_repeat_min_above_max_names_file(tmp_path):
    _require_interface()
    path = _write(tmp_path, "badrepeat", outline="  - section: c\n    intent: any\n    repeat: [5, 2]\n")
    with pytest.raises(doctypes.DoctypeError) as caught:
        doctypes.load_doctype(path)
    assert "badrepeat.yaml" in str(caught.value)


def test_D3_length_min_above_max_names_file(tmp_path):
    _require_interface()
    path = _write(
        tmp_path,
        "badlength",
        length="slides: [10, 3]",
        outline="  - section: c\n    intent: any\n",
    )
    with pytest.raises(doctypes.DoctypeError) as caught:
        doctypes.load_doctype(path)
    assert "badlength.yaml" in str(caught.value)


def test_D3_equal_bounds_are_accepted(tmp_path):
    _require_interface()
    path = _write(tmp_path, "equal", outline="  - section: c\n    intent: any\n    repeat: [2, 2]\n")
    assert doctypes.load_doctype(path).outline[0].repeat == (2, 2)


def test_D4_children_load_as_nested_entries(tmp_path):
    _require_interface()
    outline = (
        "  - section: group\n"
        "    children:\n"
        "      - section: first\n"
        "        intent: statement\n"
        "        required: true\n"
        "      - section: second\n"
        "        intent: bullets\n"
    )
    doctype = doctypes.load_doctype(_write(tmp_path, "nested", outline=outline))
    group = doctype.outline[0]
    assert group.intent is None
    assert all(isinstance(c, doctypes.OutlineEntry) for c in group.children)
    assert [c.section for c in group.children] == ["first", "second"]
    assert [c.intent for c in group.children] == ["statement", "bullets"]
    assert group.children[0].required is True


def test_D4_yaml_from_key_reads_into_from_(tmp_path):
    _require_interface()
    outline = "  - section: sum\n    intent: statement\n    fill: summary\n    from: [a, b]\n"
    doctype = doctypes.load_doctype(_write(tmp_path, "fromkey", outline=outline))
    assert doctype.outline[0].from_ == ["a", "b"]
    assert doctype.outline[0].fill == "summary"


def test_D4_entry_without_intent_or_children_is_rejected(tmp_path):
    _require_interface()
    path = _write(tmp_path, "empty", outline="  - section: nothing\n")
    with pytest.raises(doctypes.DoctypeError) as caught:
        doctypes.load_doctype(path)
    assert "empty.yaml" in str(caught.value)


def test_D5_name_differing_from_stem_names_file(tmp_path):
    _require_interface()
    path = _write(tmp_path, "actual", name="other", outline="  - section: c\n    intent: any\n")
    with pytest.raises(doctypes.DoctypeError) as caught:
        doctypes.load_doctype(path)
    assert "actual.yaml" in str(caught.value)
