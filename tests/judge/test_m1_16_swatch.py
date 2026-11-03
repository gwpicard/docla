# Intent: swatch renders one section alone on its format's page and returns its PDF, layout facts and page images.
import importlib
import struct
from pathlib import Path

import pytest

from docla.model import Document, Item, Section


def _optional(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if name != "docla.render" and not name.startswith("docla.render."):
            raise
        return None


swatch_module = _optional("docla.render.swatch")


def _require_interface() -> None:
    assert swatch_module is not None and hasattr(swatch_module, "swatch"), "docla.render.swatch.swatch must exist"
    assert hasattr(swatch_module, "SwatchRender"), "docla.render.swatch.SwatchRender must exist"


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def _slides() -> Document:
    return Document(
        front={"title": "Deck"},
        format="slides",
        sections=[
            Section(id="s1", intent="statement", title="Zephyrine opening"),
            Section(
                id="s2",
                intent="bullets",
                title="Quokka midsection",
                items=[Item(head="Marmot", body="First point about burrows"), Item(head="Ocelot", body="Second point")],
            ),
            Section(id="s3", intent="statement", title="Wombatic closing"),
        ],
    )


def _doc() -> Document:
    return Document(
        front={"title": "Report"},
        format="doc",
        sections=[
            Section(id="a1", intent="body", title="Heron overview", paragraphs=["Heron paragraph text."]),
            Section(id="a2", intent="body", title="Lemur details", paragraphs=["Lemur paragraph text."]),
            Section(id="a3", intent="callout", title="Narwhal note", paragraphs=["Narwhal callout text."]),
        ],
    )


def test_D1_slides_swatch_is_one_page_with_only_that_section(tmp_path: Path) -> None:
    _require_interface()
    result = swatch_module.swatch(_slides(), "s2", tmp_path)
    assert result.pdf.read_bytes()[:5] == b"%PDF-"
    assert len(result.pngs) == 1
    assert _png_size(result.pngs[0]) == (1920, 1080)
    assert len(result.facts.pages) == 1
    section_ids = {w.section_id for w in result.facts.words if w.section_id is not None}
    assert section_ids == {"s2"}


def test_D2_doc_swatch_is_a4_and_marks_name_only_that_section(tmp_path: Path) -> None:
    _require_interface()
    result = swatch_module.swatch(_doc(), "a2", tmp_path)
    assert len(result.pngs) == len(result.facts.pages) >= 1
    for png in result.pngs:
        width, height = _png_size(png)
        assert 1190 <= width <= 1192
        assert 1683 <= height <= 1685
    starts = [m for m in result.facts.marks if m.kind == "section" and m.edge == "start"]
    assert [m.id for m in starts] == ["a2"]
    assert {m.id for m in result.facts.marks if m.kind == "section"} == {"a2"}


def test_D3_swatch_holds_none_of_the_other_titles(tmp_path: Path) -> None:
    _require_interface()
    result = swatch_module.swatch(_slides(), "s2", tmp_path)
    text = " ".join(w.text for w in result.facts.words)
    assert "Quokka" in text
    assert "Zephyrine" not in text
    assert "Wombatic" not in text


def test_D4_same_swatch_twice_gives_identical_pdfs(tmp_path: Path) -> None:
    _require_interface()
    first = swatch_module.swatch(_slides(), "s2", tmp_path).pdf.read_bytes()
    second = swatch_module.swatch(_slides(), "s2", tmp_path).pdf.read_bytes()
    assert first == second


def test_D5_unknown_section_raises_key_error_naming_it(tmp_path: Path) -> None:
    _require_interface()
    with pytest.raises(KeyError) as excinfo:
        swatch_module.swatch(_slides(), "nope", tmp_path)
    assert "nope" in str(excinfo.value)
