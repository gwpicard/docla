# Intent: compose turns a Document into a Composition and assemble writes a render folder Typst compiles.
import importlib
import re
from pathlib import Path

import pytest

from docla.model import Citation, Document, Item, Section
from docla.render.marks import SectionMark, read_marks
from docla.render.typst import compile_pdf


def _optional(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if name != "docla.render.compose" and not name.startswith("docla.render.compose."):
            raise
        return None


compose_module = _optional("docla.render.compose")


def _require_interface() -> None:
    assert compose_module is not None, "docla.render.compose must exist"
    for name in ("compose", "assemble", "Composition", "ComposedSection", "ComposeError"):
        assert hasattr(compose_module, name), f"docla.render.compose.{name} must exist"


def _slides_doc() -> Document:
    return Document(
        front={},
        format="slides",
        sections=[
            Section(id="s1", intent="statement", title="One clear claim"),
            Section(
                id="s2",
                intent="bullets",
                title="Two points",
                items=[
                    Item(
                        head="First",
                        body="alpha body",
                        citations=[Citation(key="S1"), Citation(key="S2", locator="p3")],
                    ),
                    Item(body="beta body"),
                ],
            ),
        ],
    )


def _doc_doc() -> Document:
    return Document(
        front={},
        format="doc",
        sections=[
            Section(
                id="d1",
                intent="body",
                title="Intro",
                paragraphs=["First paragraph.", "Second paragraph."],
                source_line="Source: S1",
            ),
            Section(id="d2", intent="callout", title="Note", items=[Item(body="Mind this."), Item(body="And this.")]),
        ],
    )


def _media_boxes(pdf: Path) -> list[list[float]]:
    boxes = re.findall(rb"MediaBox\s*\[([^\]]*)\]", pdf.read_bytes())
    return [[float(part) for part in box.split()] for box in boxes]


def _build(doc: Document, tmp_path: Path):
    comp = compose_module.compose(doc)
    dest = tmp_path / "render"
    main = compose_module.assemble(comp, dest)
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, dest, pdf)
    return comp, dest, main, pdf


def _starts(main: Path, dest: Path) -> list[tuple[str, int]]:
    return [(m.id, m.page) for m in read_marks(main, dest) if isinstance(m, SectionMark) and m.edge == "start"]


def test_D1_compose_maps_slide_intents_to_components():
    _require_interface()
    comp = compose_module.compose(_slides_doc())
    assert comp.format == "slides"
    assert [(s.id, s.component) for s in comp.sections] == [("s1", "statement"), ("s2", "bullets")]


def test_D1_props_hold_exactly_the_agreed_keys_and_item_fields():
    _require_interface()
    comp = compose_module.compose(_slides_doc())
    props = comp.sections[1].props
    assert set(props) == {"id", "title", "items", "paragraphs", "source_line"}
    assert props["id"] == "s2"
    assert props["title"] == "Two points"
    assert props["items"] == [
        {"head": "First", "body": "alpha body", "cites": ["S1", "S2"]},
        {"head": "", "body": "beta body", "cites": []},
    ]
    assert props["paragraphs"] == []
    assert props["source_line"] == ""


def test_D1_missing_title_and_source_line_become_empty_strings():
    _require_interface()
    doc = Document(front={}, format="doc", sections=[Section(id="d1", intent="body", paragraphs=["Text."])])
    props = compose_module.compose(doc).sections[0].props
    assert props["title"] == ""
    assert props["source_line"] == ""
    assert props["paragraphs"] == ["Text."]


def test_D1_component_attribute_overrides_the_intent_table():
    _require_interface()
    doc = Document(
        front={},
        format="slides",
        sections=[Section(id="s1", intent="timeline", component="bullets", title="T", items=[Item(body="x")])],
    )
    comp = compose_module.compose(doc)
    assert [(s.id, s.component) for s in comp.sections] == [("s1", "bullets")]


def test_D1_m1_components_table_lists_the_four_components():
    _require_interface()
    assert compose_module.M1_COMPONENTS == {
        ("slides", "statement"): "statement",
        ("slides", "bullets"): "bullets",
        ("doc", "body"): "body",
        ("doc", "callout"): "callout",
    }


def test_D1_doc_intents_map_to_doc_components():
    _require_interface()
    comp = compose_module.compose(_doc_doc())
    assert comp.format == "doc"
    assert [(s.id, s.component) for s in comp.sections] == [("d1", "body"), ("d2", "callout")]


def test_D2_unknown_intent_for_format_raises_naming_intent_and_format():
    _require_interface()
    doc = Document(front={}, format="slides", sections=[Section(id="s1", intent="timeline", title="T")])
    with pytest.raises(compose_module.ComposeError) as caught:
        compose_module.compose(doc)
    assert "timeline" in str(caught.value)
    assert "slides" in str(caught.value)
    assert "s1" in str(caught.value)


def test_D2_doc_intent_in_slides_document_is_rejected():
    _require_interface()
    doc = Document(front={}, format="slides", sections=[Section(id="s1", intent="body")])
    with pytest.raises(compose_module.ComposeError):
        compose_module.compose(doc)


def test_D2_section_without_id_raises_compose_error():
    _require_interface()
    doc = Document(front={}, format="slides", sections=[Section(intent="statement", title="No id")])
    with pytest.raises(compose_module.ComposeError):
        compose_module.compose(doc)


def test_D2_compose_error_is_a_value_error():
    _require_interface()
    assert issubclass(compose_module.ComposeError, ValueError)


def test_D3_slides_assemble_compiles_to_two_slide_pages_with_marks(tmp_path):
    _require_interface()
    _comp, _dest, _main, pdf = _build(_slides_doc(), tmp_path)
    assert _media_boxes(pdf) == [[0.0, 0.0, 960.0, 540.0], [0.0, 0.0, 960.0, 540.0]]
    assert _starts(_main, _dest) == [("s1", 1), ("s2", 2)]


def test_D3_assemble_writes_the_render_folder(tmp_path):
    _require_interface()
    comp, dest, main, _pdf = _build(_slides_doc(), tmp_path)
    assert main == dest / "main.typ"
    assert (dest / "lib" / "marks.typ").is_file()
    assert (dest / "lib" / "theme.typ").is_file()
    for name in ("statement", "bullets"):
        assert (dest / "components" / f"{name}.typ").is_file()
    assert (dest / "composition.json").read_text() == comp.model_dump_json()


def test_D3_composition_json_round_trips():
    _require_interface()
    comp = compose_module.compose(_slides_doc())
    again = compose_module.Composition.model_validate_json(comp.model_dump_json())
    assert again == comp


def test_D4_doc_assemble_compiles_to_a4_with_ordered_marks(tmp_path):
    _require_interface()
    _comp, dest, main, pdf = _build(_doc_doc(), tmp_path)
    boxes = _media_boxes(pdf)
    assert len(boxes) >= 1
    for box in boxes:
        assert box[:2] == [0.0, 0.0]
        assert abs(box[2] - 595.28) < 0.1
        assert abs(box[3] - 841.89) < 0.1
    assert [sid for sid, _page in _starts(main, dest)] == ["d1", "d2"]


def test_D5_main_typ_sets_page_setup_for_slides_and_ink_text(tmp_path):
    _require_interface()
    main = compose_module.assemble(compose_module.compose(_slides_doc()), tmp_path / "r")
    text = main.read_text()
    assert 'page-setup.with("slides")' in text
    assert 'page-setup.with("doc")' not in text
    assert 'set text(fill: colour("ink"))' in text


def test_D5_main_typ_sets_page_setup_for_doc(tmp_path):
    _require_interface()
    main = compose_module.assemble(compose_module.compose(_doc_doc()), tmp_path / "r")
    text = main.read_text()
    assert 'page-setup.with("doc")' in text
    assert 'page-setup.with("slides")' not in text
    assert 'set text(fill: colour("ink"))' in text


def test_D5_assemble_into_existing_folder_raises_file_exists(tmp_path):
    _require_interface()
    dest = tmp_path / "taken"
    dest.mkdir()
    (dest / "keep.txt").write_text("kept")
    with pytest.raises(FileExistsError):
        compose_module.assemble(compose_module.compose(_slides_doc()), dest)
    assert (dest / "keep.txt").read_text() == "kept"
    assert not (dest / "main.typ").exists()
