# Intent: Doctype fields describe layouts, fixed text, required information, length and format twins.
import asyncio
import importlib
import importlib.util

import pytest
import yaml

from docla import write
from docla.agents.summariser import summary_sources
from docla.model import Document, Section
from docla.source.parser import parse
from docla.source.serialiser import serialise
from docla.theme import neutral_theme

try:
    doctypes = importlib.import_module("docla.doctypes")
except ImportError as error:
    if error.name != "docla.doctypes" or importlib.util.find_spec(error.name) is not None:
        raise
    doctypes = None


def need(*names):
    assert doctypes is not None, "docla.doctypes must exist"
    for name in names:
        assert hasattr(doctypes, name), f"docla.doctypes.{name} must exist"


def write_type(tmp_path, name="board", **changes):
    data = {
        "name": name,
        "format": "slides",
        "audience": "Board",
        "length": {"slides": [6, 20]},
        "questions": [],
        "checks": [],
        "checklist": [],
        "default_length": 12,
        "twin": "board-doc",
        "required_fields": [
            {"key": "author", "label": "Author", "ask": "Who is named as the author?"},
            {"key": "date", "label": "Date", "ask": "What is the date?"},
        ],
        "outline": [
            {
                "section": "summary",
                "intent": "key-numbers",
                "layouts": ["key-figures", "bullets"],
                "fill": "summary",
                "from": ["content"],
            },
            {"section": "content", "intent": "any", "layouts": ["bullets", "statement"], "repeat": [1, 8]},
            {
                "section": "notice",
                "intent": "closing",
                "fill": "fixed",
                "layouts": ["closing"],
                "text": {"title": "Confidential", "paragraphs": ["Prepared for the board."]},
            },
        ],
    }
    data.update(changes)
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_D1_fields_and_packaged_defaults(tmp_path):
    need("load_doctype", "load_doctypes", "length_unit", "walk")
    result = doctypes.load_doctype(write_type(tmp_path))
    assert result.default_length == 12 and result.length == {"slides": (6, 20)}
    assert result.twin == "board-doc"
    assert [(f.key, f.label, f.ask) for f in result.required_fields] == [
        ("author", "Author", "Who is named as the author?"),
        ("date", "Date", "What is the date?"),
    ]
    assert [(e.section, e.intent, e.layouts, e.fill) for e in result.outline] == [
        ("summary", "key-numbers", ["key-figures", "bullets"], "summary"),
        ("content", "any", ["bullets", "statement"], "facts"),
        ("notice", "closing", ["closing"], "fixed"),
    ]
    assert result.outline[1].repeat == (1, 8)
    assert result.outline[2].text.title == "Confidential"
    assert result.outline[2].text.paragraphs == ["Prepared for the board."]
    assert doctypes.length_unit("slides") == "slides"
    assert doctypes.length_unit("doc") == "pages"
    for name in ("pitch-deck", "report"):
        item = doctypes.load_doctypes()[name]
        assert item.required_fields == [] and item.default_length is None and item.twin is None
        assert all(e.layouts == [] and e.text is None for e in doctypes.walk(item.outline))


@pytest.mark.parametrize(
    "changes,layout",
    [
        ({"outline": [{"section": "x", "intent": "key-numbers", "layouts": ["chart"]}]}, "chart"),
        ({"outline": [{"section": "x", "intent": "any", "layouts": ["body"]}]}, "body"),
        ({"outline": [{"section": "x", "intent": "closing", "fill": "fixed"}]}, None),
        ({"outline": [{"section": "x", "intent": "closing", "text": {"title": "Text"}}]}, None),
        ({"outline": [{"section": "x", "intent": "any", "fill": "fixed", "text": {"title": "Text"}}]}, None),
        ({"default_length": 30}, None),
        ({"format": "doc", "default_length": 5, "outline": [{"section": "x", "intent": "body"}]}, None),
        (
            {
                "required_fields": [
                    {"key": "author", "label": "A", "ask": "A?"},
                    {"key": "author", "label": "B", "ask": "B?"},
                ]
            },
            None,
        ),
        ({"required_fields": [{"key": "Author", "label": "A", "ask": "A?"}]}, None),
    ],
)
def test_D2_invalid_fields_name_file(tmp_path, changes, layout):
    need("load_doctype", "DoctypeError")
    valid_root = tmp_path / "valid"
    valid_root.mkdir()
    try:
        doctypes.load_doctype(write_type(valid_root))
    except doctypes.DoctypeError as error:
        raise AssertionError(f"a valid doctype using the new fields must load: {error}") from None
    path = write_type(tmp_path, **changes)
    with pytest.raises(doctypes.DoctypeError) as caught:
        doctypes.load_doctype(path)
    assert path.name in str(caught.value)
    if layout:
        assert layout in str(caught.value) and "x" in str(caught.value)


def test_D3_fixed_section_and_approved_write(tmp_path):
    need("load_doctype", "fixed_section")
    kind = doctypes.load_doctype(write_type(tmp_path))
    fixed = doctypes.fixed_section(kind.outline[2])
    assert (fixed.intent, fixed.section, fixed.component, fixed.title, fixed.paragraphs, fixed.lock) == (
        "closing",
        "notice",
        "closing",
        "Confidential",
        ["Prepared for the board."],
        "all",
    )
    with pytest.raises(ValueError):
        doctypes.fixed_section(kind.outline[0])
    fixed.id = "aaaa2"
    doc = Document(
        front={"title": "Readout"},
        format="slides",
        sections=[Section(id="aaaa1", intent="statement", section="content", title="A clear statement"), fixed],
    )
    path = tmp_path / "deck.md"
    path.write_text(serialise(doc), encoding="utf-8")

    class Fake:
        def __init__(self):
            self.drafts = []

        async def gather(self, extracted):
            return []

        async def outline(self, *args):
            raise AssertionError("approved outline must not be replanned")

        def writer(self, facts, document):
            self.document = document
            return self

        async def draft(self, job):
            self.drafts.append(job.section_id)
            return next(s for s in self.document.sections if s.id == job.section_id).model_copy(deep=True)

        async def repair(self, *args, **kwargs):
            raise AssertionError("clean sections must not be repaired")

    fake = Fake()
    agents = write.Agents(gather=fake.gather, outline=fake.outline, writer=fake.writer)
    assert (
        asyncio.run(write.run_write(path, agents=agents, theme=neutral_theme(), out=tmp_path / "out", approve=True))
        == 0
    )
    assert fake.drafts == ["aaaa1"]
    result, _ = parse(path.read_text(encoding="utf-8"))
    assert (result.sections[1].title, result.sections[1].paragraphs, result.sections[1].lock) == (
        "Confidential",
        ["Prepared for the board."],
        "all",
    )


def test_D4_resolve_twins_and_errors(tmp_path):
    need("load_doctype", "resolve_doctype", "DoctypeError")
    board = doctypes.load_doctype(write_type(tmp_path))
    doc = doctypes.load_doctype(
        write_type(
            tmp_path,
            "board-doc",
            format="doc",
            length={"pages": [1, 10]},
            default_length=5,
            twin="board",
            outline=[{"section": "content", "intent": "any", "layouts": ["body", "callout"]}],
        )
    )
    solo = doctypes.load_doctype(write_type(tmp_path, "solo", twin=None))
    kinds = {"board": board, "board-doc": doc, "solo": solo}
    assert doctypes.resolve_doctype(kinds, "board", "slides").name == "board"
    assert doctypes.resolve_doctype(kinds, "board", "doc").name == "board-doc"
    assert doctypes.resolve_doctype(kinds, "board-doc", "slides").name == "board"
    for name, fmt in [("solo", "doc"), ("nope", "slides")]:
        with pytest.raises(doctypes.DoctypeError) as caught:
            doctypes.resolve_doctype(kinds, name, fmt)
        assert name in str(caught.value)
        if name == "solo":
            assert "doc" in str(caught.value)


def test_D5_walk_and_summary_sources(tmp_path):
    need("load_doctype", "walk")
    outline = [
        {
            "section": "group",
            "children": [
                {"section": "content", "intent": "any"},
                {"section": "nested", "children": [{"section": "other", "intent": "any"}]},
            ],
        },
        {"section": "summary", "intent": "any", "fill": "summary", "from": ["content"]},
    ]
    kind = doctypes.load_doctype(write_type(tmp_path, outline=outline))
    assert [e.section for e in doctypes.walk(kind.outline)] == ["group", "content", "nested", "other", "summary"]
    sections = [
        Section(id="aaaa1", intent="bullets", section="summary"),
        Section(id="aaaa2", intent="bullets", section="content"),
        Section(id="aaaa3", intent="bullets", section="other"),
        Section(id="aaaa4", intent="bullets", section="content"),
    ]
    document = Document(front={}, format="slides", sections=sections)
    assert summary_sources(document, kind) == {"aaaa1": [sections[1], sections[3]]}
