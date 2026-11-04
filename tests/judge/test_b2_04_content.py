# Intent: carry section content to components while preserving M1 props and marks.
import importlib
import inspect

import pdfplumber

from docla.model import Citation, Document, Item, Section
from docla.render.marks import SectionMark, read_marks
from docla.render.typst import compile_pdf

try:
    compose = importlib.import_module("docla.render.compose")
except ImportError as error:
    if error.name != "docla.render.compose" and not str(error.name).startswith("docla.render.compose."):
        raise
    compose = None


def _composition():
    assert compose is not None and hasattr(compose, "compose"), "compose must exist"
    return compose.compose(Document(front={}, format="slides", sections=[
        Section(id="s1", intent="bullets", title="Points", data={"k": "Amber", "n": 3},
                image="ignored.png", icons=["ignored"], items=[
                    Item(head="First", body="Alpha", citations=[Citation(key="S1", locator="p. 4"), Citation(key="S2")]),
                    Item(body="Beta"), Item(body="Gamma", citations=[Citation(key="S3", locator="p. 9")]),
                ]),
        Section(id="s2", intent="statement", title="Claim"),
    ]))


def test_D1_props_remain_exactly_the_m1_shape():
    assert _composition().sections[0].props == {
        "id": "s1", "title": "Points", "paragraphs": [], "source_line": "",
        "items": [{"head": "First", "body": "Alpha", "cites": ["S1", "S2"]},
                  {"head": "", "body": "Beta", "cites": []},
                  {"head": "", "body": "Gamma", "cites": ["S3"]}],
    }


def test_D2_content_carries_data_and_aligned_citations():
    sections = _composition().sections
    assert hasattr(sections[0], "content"), "ComposedSection.content must exist"
    assert sections[0].content == {
        "data": {"k": "Amber", "n": 3}, "image": "", "icons": [],
        "citations": [[{"key": "S1", "locator": "p. 4"}, {"key": "S2", "locator": None}],
                      [], [{"key": "S3", "locator": "p. 9"}]],
    }
    assert sections[1].content == {"data": None, "image": "", "citations": [], "icons": []}


def test_D3_library_component_reads_data_and_props(tmp_path):
    comp = _composition()
    assert hasattr(comp.sections[0], "content"), "ComposedSection.content must exist"
    assert compose is not None and hasattr(compose, "assemble"), "assemble must exist"
    assert "library" in inspect.signature(compose.assemble).parameters, "assemble must accept a library"
    library = tmp_path / "library"
    library.mkdir()
    (library / "reader.typ").write_text('#let reader(sec) = [#sec.title: #sec.data.k]')
    (library / "reader.yaml").write_text(
        "name: reader\nformat: slides\nlabel: Reader\nintents: [bullets]\ncapacity: {}\nelements: [title]\n"
    )
    section = comp.sections[0].model_copy(update={"component": "reader"})
    comp = comp.model_copy(update={"sections": [section]})
    dest = tmp_path / "render"
    main = compose.assemble(comp, dest, library=library)
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, dest, pdf)
    with pdfplumber.open(pdf) as result:
        assert [word["text"] for page in result.pages for word in page.extract_words()] == ["Points:", "Amber"]


def test_D4_json_round_trip_keeps_content():
    comp = _composition()
    assert hasattr(comp.sections[0], "content"), "ComposedSection.content must exist"
    assert compose is not None and hasattr(compose, "Composition")
    restored = compose.Composition.model_validate_json(comp.model_dump_json())
    assert restored == comp
    assert restored.sections[0].content["citations"][0][1] == {"key": "S2", "locator": None}


def test_D4_m1_slide_and_doc_marks(tmp_path):
    docs = [
        Document(front={}, format="slides", sections=[
            Section(id="s1", intent="statement", title="Claim"),
            Section(id="s2", intent="bullets", title="Points", items=[Item(body="Alpha")]),
        ]),
        Document(front={}, format="doc", sections=[
            Section(id="d1", intent="body", title="Intro", paragraphs=["First paragraph."]),
            Section(id="d2", intent="callout", title="Note", items=[Item(body="Mind this.")]),
        ]),
    ]
    assert compose is not None and hasattr(compose, "compose") and hasattr(compose, "assemble")
    for doc, expected in zip(docs, [[("s1", 1), ("s2", 2)], [("d1", 1), ("d2", 1)]]):
        dest = tmp_path / doc.format
        main = compose.assemble(compose.compose(doc), dest)
        pdf = tmp_path / f"{doc.format}.pdf"
        compile_pdf(main, dest, pdf)
        assert [(m.id, m.page) for m in read_marks(main, dest)
                if isinstance(m, SectionMark) and m.edge == "start"] == expected
        assert pdf.stat().st_size > 0
