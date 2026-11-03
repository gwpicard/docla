# Intent: join joins PDF facts to semantic marks so every word and shape knows its section and role.
import hashlib
import importlib
import shutil
from pathlib import Path


def _optional(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if name != "docla.facts" and not name.startswith("docla.facts."):
            raise
        return None


layout = _optional("docla.facts.layout")
models = _optional("docla.facts.models")
pdf_facts = _optional("docla.facts.pdf")

from docla.render.kit import lib_dir  # noqa: E402
from docla.render.marks import ElementMark, SectionMark, read_marks  # noqa: E402
from docla.render.typst import compile_pdf  # noqa: E402


def _require_interface() -> None:
    assert layout is not None, "docla.facts.layout must exist"
    for name in ("join", "layout_facts", "LayoutFacts", "PlacedWord", "PlacedShape"):
        assert hasattr(layout, name), f"docla.facts.layout.{name} must exist"
    assert models is not None and pdf_facts is not None, "docla.facts.models and docla.facts.pdf must exist"


def _build(tmp_path: Path, source: str):
    _require_interface()
    shutil.copytree(lib_dir(), tmp_path / "lib")
    main = tmp_path / "main.typ"
    main.write_text(source)
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, tmp_path, pdf)
    return main, pdf, layout.layout_facts(pdf, main, tmp_path)


def _word(facts, text: str):
    found = [w for w in facts.words if w.text == text]
    assert len(found) == 1, f"expected exactly one word {text!r}, found {len(found)}"
    return found[0]


def _fact_word(text: str, page: int, cx: float, cy: float):
    box = models.FactBox(page=page, x0=cx - 5, y0=cy - 5, x1=cx + 5, y1=cy + 5)
    return models.Word(text=text, font="F", size=10.0, colour=None, box=box, baseline=cy + 3)


def _page(page: int, words):
    return models.PageFacts(page=page, width=595.0, height=842.0, words=list(words), shapes=[])


def _join(words_by_page: dict[int, list], marks):
    _require_interface()
    pages = [_page(p, ws) for p, ws in words_by_page.items()]
    result = layout.join(pages, marks, "0" * 64)
    return {w.text: w for w in result.words}


def _start(id_: str, page: int, y: float) -> SectionMark:
    return SectionMark(kind="section", id=id_, edge="start", page=page, x=0, y=y)


def _end(id_: str, page: int, y: float) -> SectionMark:
    return SectionMark(kind="section", id=id_, edge="end", page=page, x=0, y=y)


def _element(role: str, id_: str, x: float, y: float, w: float, h: float, page: int = 1) -> ElementMark:
    return ElementMark(kind="element", role=role, id=id_, page=page, x=x, y=y, w=w, h=h)


def test_D1_word_inside_title_element_gets_role_and_section(tmp_path):
    source = """\
#import "/lib/marks.typ": section, el
#set page(paper: "a4")
#section("s1")[#el("title", "s1")[Hello]]
"""
    _, _, facts = _build(tmp_path, source)
    word = _word(facts, "Hello")
    assert word.role == "title"
    assert word.section_id == "s1"


def test_D1_join_assigns_role_from_containing_element_box():
    words = {1: [_fact_word("in", 1, 50, 35), _fact_word("right", 1, 200, 35), _fact_word("other", 2, 50, 35)]}
    placed = _join(words, [_element("title", "s1", 10, 20, 100, 30)])
    assert (placed["in"].role, placed["in"].section_id) == ("title", "s1")
    assert (placed["right"].role, placed["right"].section_id) == (None, None)
    assert (placed["other"].role, placed["other"].section_id) == (None, None)


def test_D4_join_innermost_element_is_the_smallest_containing_box():
    marks = [_element("body", "s1", 0, 0, 300, 300), _element("item", "s1", 100, 100, 50, 20)]
    words = {1: [_fact_word("inner", 1, 120, 110), _fact_word("outer", 1, 20, 20)]}
    placed = _join(words, marks)
    assert placed["inner"].role == "item"
    assert placed["outer"].role == "body"


def test_D2_join_cut_points_use_page_then_y_and_end_marks():
    marks = [_start("a", 1, 100), _end("a", 1, 200), _start("b", 1, 300), _end("b", 2, 100)]
    words = {
        1: [
            _fact_word("before", 1, 50, 50),
            _fact_word("ina", 1, 50, 150),
            _fact_word("gap", 1, 50, 250),
            _fact_word("inb", 1, 50, 350),
        ],
        2: [_fact_word("inb2", 2, 50, 50), _fact_word("after", 2, 50, 300)],
    }
    placed = _join(words, marks)
    assert placed["before"].section_id is None
    assert placed["ina"].section_id == "a"
    assert placed["gap"].section_id is None
    assert placed["inb"].section_id == "b"
    assert placed["inb2"].section_id == "b"
    assert placed["after"].section_id is None
    assert all(placed[t].role is None for t in placed)


def test_D2_words_across_pages_follow_section_start_marks(tmp_path):
    source = """\
#import "/lib/marks.typ": section
#set page(paper: "a4")
#section("a")[#for i in range(40) [#("aw" + str(i)) #parbreak()]]
#section("b")[#for i in range(5) [#("bw" + str(i)) #parbreak()]]
"""
    main, _, facts = _build(tmp_path, source)
    starts = {m.id: m for m in facts.marks if isinstance(m, SectionMark) and m.edge == "start"}
    assert starts["b"].page == 2
    a_words = [w for w in facts.words if w.text.startswith("aw")]
    b_words = [w for w in facts.words if w.text.startswith("bw")]
    assert len(a_words) == 40 and len(b_words) == 5
    assert {w.box.page for w in a_words} == {1, 2}
    assert all(w.section_id == "a" for w in a_words)
    assert all(w.section_id == "b" for w in b_words)


def test_D3_word_before_first_section_start_has_no_section_or_role(tmp_path):
    source = """\
#import "/lib/marks.typ": section
#set page(paper: "a4")
Preamble

#section("s1")[Inside]
"""
    _, _, facts = _build(tmp_path, source)
    pre = _word(facts, "Preamble")
    assert pre.section_id is None
    assert pre.role is None
    inside = _word(facts, "Inside")
    assert inside.section_id == "s1"
    assert inside.role is None


def test_D4_item_inside_body_gets_item_and_rest_of_body_gets_body(tmp_path):
    source = """\
#import "/lib/marks.typ": section, el
#set page(paper: "a4")
#section("s1")[#el("body", "s1")[Intro #el("item", "s1")[ITEMWORD] Outro]]
"""
    _, _, facts = _build(tmp_path, source)
    assert _word(facts, "ITEMWORD").role == "item"
    assert _word(facts, "Intro").role == "body"
    assert _word(facts, "Outro").role == "body"
    assert {_word(facts, t).section_id for t in ("ITEMWORD", "Intro", "Outro")} == {"s1"}


def test_D5_filled_rectangle_inside_frame_becomes_placed_shape(tmp_path):
    source = """\
#import "/lib/marks.typ": section, el
#set page(paper: "a4")
#section("s1")[
  #el("frame", "s1", rect(width: 100pt, height: 40pt, fill: rgb("#FF0000"), stroke: none))
  #rect(width: 60pt, height: 20pt, fill: rgb("#0000FF"), stroke: none)
]
"""
    _, _, facts = _build(tmp_path, source)
    red = [s for s in facts.shapes if s.fill == "#FF0000"]
    blue = [s for s in facts.shapes if s.fill == "#0000FF"]
    assert len(red) == 1 and len(blue) == 1
    assert isinstance(red[0], layout.PlacedShape)
    assert red[0].kind == "rect"
    assert (red[0].role, red[0].section_id) == ("frame", "s1")
    assert (blue[0].role, blue[0].section_id) == (None, "s1")


def test_D6_layout_facts_records_pdf_digest_and_marks(tmp_path):
    source = """\
#import "/lib/marks.typ": section, el
#set page(paper: "a4")
#section("s1")[#el("title", "s1")[Hello]]
"""
    main, pdf, facts = _build(tmp_path, source)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert len(digest) == 64
    assert facts.pdf_sha256 == digest
    expected = read_marks(main, tmp_path)
    assert len(expected) == 3
    assert facts.marks == expected


def test_D6_layout_facts_uses_the_given_extractor(tmp_path):
    source = """\
#import "/lib/marks.typ": section, el
#set page(paper: "a4")
#section("s1")[#el("title", "s1")[Hello]]
"""
    _require_interface()
    shutil.copytree(lib_dir(), tmp_path / "lib")
    main = tmp_path / "main.typ"
    main.write_text(source)
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, tmp_path, pdf)
    element = next(m for m in read_marks(main, tmp_path) if isinstance(m, ElementMark))

    class FakeFacts:
        def extract(self, path: Path):
            assert path == pdf
            return [_page(1, [_fact_word("fake", 1, element.x + 1, element.y + 1)])]

    facts = layout.layout_facts(pdf, main, tmp_path, FakeFacts())
    assert [w.text for w in facts.words] == ["fake"]
    assert (facts.words[0].role, facts.words[0].section_id) == ("title", "s1")
