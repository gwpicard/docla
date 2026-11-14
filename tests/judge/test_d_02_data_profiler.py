# Intent: Profile table data and doctype defaults into an evidenced brief and read-back.
import importlib
import importlib.util

import pytest

from docla.doctypes import load_doctype
from docla.model.brief import Brief, BriefScope, FieldProvenance
from docla.sources import extract

try:
    profiler = importlib.import_module("docla.intake.profile")
except ImportError as error:
    if error.name not in {"docla.intake", "docla.intake.profile"}:
        raise
    if importlib.util.find_spec("docla.intake") is not None:
        if importlib.util.find_spec("docla.intake.profile") is not None:
            raise
    profiler = None


def _require():
    assert profiler is not None and hasattr(profiler, "profile"), "profiler must exist"
    for name in ("Profile", "ReadBackItem", "Conflict"):
        assert hasattr(profiler, name), f"profiler.{name} must exist"


def _doctype(path, fmt="slides"):
    path.mkdir(parents=True, exist_ok=True)
    unit, count = ("slides", 12) if fmt == "slides" else ("pages", 8)
    file = path / "board.yaml"
    file.write_text(
        f"name: board\nformat: {fmt}\naudience: Board members\n"
        f"length: {{{unit}: [4, 20]}}\ndefault_length: {count}\n"
        "required_fields:\n  - key: author\n    label: Author\n    ask: Who wrote it?\n"
        "  - key: date\n    label: Date\n    ask: What date?\n"
        "questions: []\noutline:\n  - section: content\n    intent: any\n"
        "checks: []\nchecklist: []\n",
        encoding="utf-8",
    )
    return load_doctype(file)


def _sales(path, extra=""):
    folder = path / "sources"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sales.csv").write_text(
        'Initiative,Revenue,Margin,Closed\nPartner channel,"£1,234,500",12.5%,2026-07-15\n'
        'Pricing reset,"£980,000",8.0%,2026-09-30\n' + extra,
        encoding="utf-8",
    )


def _run(path):
    return profiler.profile(
        extract(path), fmt="slides", doctype=_doctype(path / "types"), request="Q3 sales for the board"
    )


def test_D1_brief_values(tmp_path):
    _require()
    _sales(tmp_path)
    result = _run(tmp_path)
    brief = result.brief
    assert isinstance(result, profiler.Profile)
    assert brief.request == "Q3 sales for the board"
    assert brief.doctype == "board"
    assert brief.audience.who == "Board members"
    assert (brief.scope.period, brief.scope.currency) == ("Q3 2026", "GBP")
    assert [topic.name for topic in brief.topics] == ["Partner channel", "Pricing reset"]
    assert brief.topics[0].data_ref == "sales!B2:C2"
    assert [metric.name for metric in brief.metrics] == ["Revenue", "Margin"]
    assert brief.metrics[0].sources == ["sales!B2:B3"]
    assert brief.length.count == 12
    assert [element.element for element in brief.required_elements] == ["author", "date"]
    for field in ("key_message", "ask", "tone"):
        assert getattr(brief, field) is None
        assert brief.status(field) is None


def test_D2_provenance_and_read_back(tmp_path):
    _require()
    _sales(tmp_path)
    result = _run(tmp_path)
    ids = {fact.locator: fact.id for fact in result.facts}
    assert all(ids[locator] for locator in ("sales!D2", "sales!D3", "sales!B2"))
    assert result.brief.provenance["scope"].evidence == [ids["sales!D2"], ids["sales!D3"], ids["sales!B2"]]
    for field in ("scope", "topics", "metrics"):
        assert result.brief.status(field) == "inferred"
        assert result.brief.provenance[field].evidence
    for field in ("doctype", "audience", "length", "required_elements"):
        assert result.brief.status(field) == "defaulted"
        assert result.brief.provenance[field].evidence == ["doctype:board"]
    assert [item.field for item in result.read_back] == [
        "doctype",
        "audience",
        "scope",
        "topics",
        "metrics",
        "length",
        "required_elements",
    ]
    scope = next(item for item in result.read_back if item.field == "scope")
    assert isinstance(scope, profiler.ReadBackItem)
    assert "Q3 2026" in scope.text and "GBP" in scope.text
    assert "S1 sales!D2" in scope.sources
    assert scope.evidence == result.brief.provenance["scope"].evidence
    assert scope.status == "inferred"


def test_D3_conflicts_and_scope_boundaries(tmp_path):
    _require()
    _sales(tmp_path)
    (tmp_path / "sources" / "targets.csv").write_text(
        'Initiative,Revenue\nPartner channel,"£1,300,000"\n', encoding="utf-8"
    )
    result = _run(tmp_path)
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert isinstance(conflict, profiler.Conflict)
    assert (conflict.field, conflict.label, conflict.header) == ("metrics", "Partner channel", "Revenue")
    assert conflict.values == ["£1,234,500", "£1,300,000"]
    facts = {fact.id: fact for fact in result.facts}
    assert len(conflict.evidence) == 2
    assert [facts[id_].locator for id_ in conflict.evidence] == ["sales!B2", "targets!B2"]
    assert conflict.sources == ["S1 sales!B2", "S2 targets!B2"]
    assert [topic.name for topic in result.brief.topics] == ["Partner channel", "Pricing reset"]
    assert [metric.name for metric in result.brief.metrics] == ["Revenue", "Margin"]
    _sales(tmp_path, "New initiative,$5,2%,2026-10-02\n")
    changed = _run(tmp_path)
    assert changed.brief.scope.period == "2026-07-15 to 2026-10-02"
    assert changed.brief.scope.currency is None


def test_D4_existing_provenance_and_non_table_files(tmp_path):
    _require()
    _sales(tmp_path)
    (tmp_path / "sources" / "notes.md").write_text("Notes for the meeting.\n", encoding="utf-8")
    brief = Brief(
        format="slides",
        request="Original request",
        scope=BriefScope(period="FY26"),
        provenance={
            "scope": FieldProvenance(status="confirmed", person="owner"),
            "audience": FieldProvenance(status="skipped"),
        },
    )
    original = brief.model_copy(deep=True)
    result = profiler.profile(
        extract(tmp_path), fmt="slides", doctype=_doctype(tmp_path / "types"), request="Ignored", brief=brief
    )
    assert brief == original
    assert result.brief.request == "Original request"
    assert result.brief.scope == original.scope
    assert result.brief.audience is None
    assert result.brief.provenance["scope"] == original.provenance["scope"]
    assert result.brief.provenance["audience"] == original.provenance["audience"]
    assert not {"scope", "audience"} & {item.field for item in result.read_back}
    assert result.files == ["notes.md"]
    assert result.facts and all(fact.source_key == "S2" for fact in result.facts)
    no_type = profiler.profile(extract(tmp_path), fmt="slides")
    assert all(no_type.brief.status(field) is None for field in ("audience", "length", "required_elements"))


def test_D5_format_and_mismatch(tmp_path):
    _require()
    _sales(tmp_path)
    slides = _run(tmp_path)
    doc = profiler.profile(
        extract(tmp_path), fmt="doc", doctype=_doctype(tmp_path / "doc-types", "doc"), request="Q3 sales for the board"
    )
    assert doc.brief.length.count == 8
    assert "pages" in next(item.text for item in doc.read_back if item.field == "length")
    assert doc.brief.model_dump(exclude={"format", "length"}) == slides.brief.model_dump(exclude={"format", "length"})
    with pytest.raises(ValueError):
        profiler.profile(extract(tmp_path), fmt="slides", brief=Brief(format="doc"))
