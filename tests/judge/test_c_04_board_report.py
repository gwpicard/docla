# Intent: Packaged board report twins provide matching outlines for slides and documents.
from pathlib import Path

import yaml

try:
    from docla import cli, doctypes
    from docla.model import Document, Item, Section
    from docla.render import compose
    from docla.source import ids
except ImportError as error:
    if error.name not in {
        "docla",
        "docla.cli",
        "docla.doctypes",
        "docla.model",
        "docla.model.Document",
        "docla.model.Item",
        "docla.model.Section",
        "docla.render",
        "docla.render.compose",
        "docla.source",
        "docla.source.ids",
    }:
        raise
    cli = doctypes = Document = Item = Section = compose = ids = None

ROOT = Path(__file__).resolve().parents[2]
NAMES = ["cover", "agenda", "summary", "performance", "initiatives", "profitability", "risks", "decisions", "notice"]
DECK_LAYOUTS = ["cover", "agenda", "key-figures", "chart", "key-figures", "chart", "bullets", "statement", "closing"]


def _library():
    assert doctypes is not None and hasattr(doctypes, "packaged_doctypes"), "packaged_doctypes must exist"
    library = doctypes.packaged_doctypes()
    assert "board-report" in library and "board-report-doc" in library
    return library


def test_D1_packaged_metadata_and_legacy_types():
    library = _library()
    for name, fmt, default, unit, bounds, twin in [
        ("board-report", "slides", 12, "slides", (6, 20), "board-report-doc"),
        ("board-report-doc", "doc", 8, "pages", (4, 20), "board-report"),
    ]:
        kind = library[name]
        assert (kind.name, kind.format, kind.default_length, kind.length[unit], kind.twin) == (
            name,
            fmt,
            default,
            bounds,
            twin,
        )
        assert [part.section for part in kind.outline] == NAMES
        assert [field.key for field in kind.required_fields] == ["author", "date"]
        assert [question.key for question in kind.questions] == ["period", "comparison"]
    assert set(doctypes.load_doctypes()) == {"pitch-deck", "report"}


def test_D2_outline_properties():
    library = _library()
    for name in ("board-report", "board-report-doc"):
        parts = {part.section: part for part in library[name].outline}
        assert {name for name, part in parts.items() if part.required} == {
            "cover",
            "summary",
            "performance",
            "decisions",
        }
        assert parts["agenda"].fill == parts["summary"].fill == "summary"
        assert parts["agenda"].from_ == ["performance", "initiatives", "profitability", "risks"]
        assert parts["notice"].fill == "fixed"
        assert parts["notice"].text.title == "Confidential"
        assert parts["notice"].text.paragraphs == ["Prepared for the board. Not for circulation."]
        assert parts["initiatives"].repeat == (1, 8)
    assert [part.layouts[0] for part in library["board-report"].outline] == DECK_LAYOUTS
    assert [part.layouts for part in library["board-report-doc"].outline] == [
        ["body"],
        ["callout"],
        ["callout"],
        ["body"],
        ["body"],
        ["body"],
        ["body"],
        ["callout"],
        ["body"],
    ]


def test_D3_resolve_twins():
    library = _library()
    assert hasattr(doctypes, "resolve_doctype"), "resolve_doctype must exist"
    assert doctypes.resolve_doctype(library, "board-report", "doc").name == "board-report-doc"
    assert doctypes.resolve_doctype(library, "board-report-doc", "slides").name == "board-report"


def _build(kind, tmp_path):
    assert all(value is not None for value in (Document, Item, Section, compose, ids))
    assert hasattr(doctypes, "fixed_section"), "fixed_section must exist"
    sections = []
    chooser = compose.default_chooser()
    for part in kind.outline:
        if part.fill == "fixed":
            sections.append(doctypes.fixed_section(part))
            continue
        layout = part.layouts[0]
        intent = part.intent
        if intent == "any":
            intent = next(
                key[0]
                for key, entries in chooser.entries.items()
                if key[1] == kind.format and any(entry.component == layout for entry in entries)
            )
        items = []
        if layout in {"bullets", "agenda", "comparison"}:
            items = [Item(body="First"), Item(body="Second")]
        elif layout == "key-figures":
            items = [Item(head=str(number), body="Result") for number in (1, 2, 3)]
        data = None
        if layout in {"chart", "table"}:
            fixture = ROOT / "tests" / "fixtures" / "components" / f"{layout}.yaml"
            data = yaml.safe_load(fixture.read_text())["data"]
        sections.append(
            Section(
                intent=intent,
                section=part.section,
                component=layout,
                title="Title",
                paragraphs=["A short paragraph."],
                items=items,
                data=data,
            )
        )
    document = Document(front={}, format=kind.format, sections=sections)
    return ids.stamp(document, ids.IdStore(tmp_path / f"{kind.name}.json"))[0]


def test_D4_compose_both_outlines(tmp_path):
    library = _library()
    deck = _build(library["board-report"], tmp_path)
    doc = _build(library["board-report-doc"], tmp_path)
    assert [section.component for section in compose.compose(deck).sections] == DECK_LAYOUTS
    assert [section.component for section in compose.compose(doc).sections] == [
        "body",
        "callout",
        "callout",
        "body",
        "body",
        "body",
        "body",
        "callout",
        "body",
    ]
    assert doc.sections[-1].title == "Confidential"
    assert doc.sections[-1].lock == "all"
    assert compose.compose(doc).sections[-1].props["title"] == "Confidential"


def test_D5_theme_test_output(capsys, monkeypatch):
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    monkeypatch.chdir(ROOT)
    try:
        code = cli.main(["theme", "test"])
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr()
    assert code == 0, (output.out, output.err)
    lines = output.out.splitlines()
    assert len(lines) == 5
    assert lines[2] == "ok doctypes" or lines[2].startswith("ok doctypes [")
