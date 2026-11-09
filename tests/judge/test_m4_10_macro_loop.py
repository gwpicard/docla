# Intent: Build, inspect and repair a whole deck before storing its final version.
import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

from docla.agents.writer import DraftItem, SectionDraft
from docla.checks.catalogue import all_rules
from docla.checks.engine import CHECKS, make_finding
from docla.doctypes import load_doctype
from docla.model import Item, Patch, PatchOp, Rule
from docla.source.parser import parse
from docla.theme import neutral_theme

try:
    from docla.loop import macro
except ImportError as error:
    if error.name not in ("docla.loop", "docla.loop.macro"):
        raise
    if importlib.util.find_spec("docla.loop.macro") is not None:
        raise
    macro = None

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/seeded-defects"
SHORT_ITEMS = [
    Item(head="Inspection intervals", body="were set in 2019."),
    Item(head="Corrosion data", body="sits in three systems."),
    Item(head="Coating records", body="are kept on paper."),
]


def interface():
    assert macro is not None, "docla.loop.macro must exist"
    assert hasattr(macro, "MacroContext") and hasattr(macro, "build_document")
    return macro


class Writer:
    def __init__(self, doc, events=None):
        self.sections = {s.id: s for s in doc.sections}
        self.drafts = []
        self.repairs = []
        self.events = events

    async def draft(self, job):
        self.drafts.append(job.section_id)
        if self.events is not None:
            self.events.append(("draft", job.section_id))
        return self.sections[job.section_id].model_copy(deep=True)

    async def repair(self, job, state, history, *, strategy=None):
        self.repairs.append(job.section_id)
        assert job.section_id == "c4e10", "only the overflowing section should need repair"
        return Patch(
            base_rev=0,
            author="ai",
            reason="shorten",
            ops=[
                PatchOp(
                    op="set_fields",
                    section_id=job.section_id,
                    fields={"items": [item.model_dump() for item in SHORT_ITEMS]},
                )
            ],
        )


def seeded_deck():
    overflow = (FIXTURES / "geo.text-fits/fail/doc.md").read_text().split("::: {#c4e10", 1)[1]
    overflow = "::: {#c4e10" + overflow.replace('intent="bullets"', 'intent="bullets" section="content"', 1)
    text = (
        "---\ndoctype: pitch-deck\nformat: slides\ntitle: Readout\n---\n\n"
        "## Sources\n\n- [S1] workshop.vtt, transcript\n\n"
    )
    text += (
        '::: {#opener .section intent="statement" section="opener"}\n## The finding\n\nA finding. [S1 00:41]\n:::\n\n'
    )
    for i in range(1, 5):
        text += (
            f'::: {{#cards{i} .section intent="card-set" section="content"}}\n## Findings {i}\n\n'
            "- **First** A finding. [S1 00:41]\n- **Second** A finding. [S1 00:41]\n"
            "- **Third** A finding. [S1 00:41]\n:::\n\n"
        )
    text += (
        '::: {#statement .section intent="statement" section="content"}\n'
        "## The result\n\nA finding. [S1 00:41]\n:::\n\n"
    )
    text += (
        overflow + '\n::: {#ask .section intent="statement" section="ask"}\n## The ask\n\nA decision. [S1 00:41]\n:::\n'
    )
    return text


def build(tmp_path, text, events=None, **options):
    m = interface()
    path = tmp_path / "deck.md"
    path.write_text(text, encoding="utf-8")
    doc, findings = parse(text)
    assert not findings
    writer = Writer(doc, events)
    ctx = m.MacroContext(doc_path=path, theme=neutral_theme(), writer=writer, workdir=tmp_path / "work", **options)
    version = asyncio.run(m.build_document(doc, ctx))
    folder = tmp_path / "deck.versions" / "v1"
    assert folder.is_dir()
    manifest = json.loads((folder / "manifest.json").read_text())
    composition = json.loads((folder / "composition.json").read_text())
    return version, path, writer, manifest, composition


def test_D1_seeded_deck_clears_in_two_rounds(tmp_path):
    version, _, writer, manifest, comp = build(tmp_path, seeded_deck(), macro_rounds=2)
    assert version is not None
    assert manifest["findings"]["error"] == 0
    assert manifest["findings"]["warning"] == 0
    assert manifest["residual"] == []
    components = [s["component"] for s in comp["sections"]]
    assert all(len(set(components[i : i + 3])) > 1 for i in range(len(components) - 2))
    assert writer.repairs == ["c4e10"]


def test_D2_repairs_are_written_to_working_file(tmp_path):
    _, path, _, _, _ = build(tmp_path, seeded_deck(), macro_rounds=2)
    doc, findings = parse(path.read_text())
    assert not [f for f in findings if f.severity == "error"]
    assert next(s for s in doc.sections if s.id == "c4e10").items == SHORT_ITEMS
    assert any(
        s.component == "bullets" and (s.because or "").startswith("router: switched from cards")
        for s in doc.sections
        if s.intent == "card-set"
    )


def test_D3_engine_finding_is_reported_once(tmp_path, monkeypatch):
    interface()

    class EngineCheck:
        tier = "source"

        def run(self, ctx, rule):
            return [make_finding(rule, ctx, message="engine defect", section_id="statement")]

    monkeypatch.setitem(CHECKS, "judge-macro-engine", EngineCheck())
    rule = Rule.model_validate(
        {
            "id": "judge.engine",
            "title": "Engine defect",
            "origin": "manual",
            "strength": "hard",
            "status": "active",
            "severity": "error",
            "tier": "source",
            "loop": "macro",
            "check": {"kind": "judge-macro-engine"},
            "remedy": {"class": "engine", "hint": "fix engine"},
            "provenance": {},
        }
    )
    _, _, writer, manifest, _ = build(tmp_path, seeded_deck(), rules=all_rules() + [rule])
    assert "statement" not in writer.repairs
    assert [r for r in manifest["residual"] if r["finding"] == "93172b30065b"] == [
        {"finding": "93172b30065b", "reason": "engine"}
    ]


def test_D4_unfixable_sequence_stops_after_one_look(tmp_path, monkeypatch):
    m = interface()
    counting_look = Mock(wraps=m.look)
    monkeypatch.setattr(m, "look", counting_look)
    text = (FIXTURES / "deck.no-component-three-running/fail/doc.md").read_text()
    _, _, writer, manifest, _ = build(tmp_path, text)
    assert counting_look.call_count == 1
    assert writer.repairs == []
    assert {"finding": "23a098432b4c", "reason": "no progress"} in manifest["residual"]


def test_D5_summary_follows_all_drafts_and_is_saved(tmp_path):
    interface()
    yaml = tmp_path / "mini.yaml"
    yaml.write_text(
        "name: mini\nformat: slides\naudience: Readers\nlength: {slides: [1, 10]}\n"
        "questions: []\noutline:\n  - section: agenda\n    intent: bullets\n    fill: summary\n"
        "    from: [content]\n  - section: content\n    intent: bullets\nchecks: []\nchecklist: []\n"
    )
    doctype = load_doctype(yaml)
    text = (
        "---\ndoctype: mini\nformat: slides\ntitle: Readout\n---\n\n## Sources\n\n- [S1] source\n\n"
        '::: {#agenda .section intent="bullets" section="agenda"}\n## Agenda\n\n- Old. [S1]\n:::\n\n'
        '::: {#one .section intent="bullets" section="content"}\n## One\n\n- First. [S1]\n:::\n\n'
        '::: {#two .section intent="bullets" section="content"}\n## Two\n\n- Second. [S1]\n:::\n'
    )
    events = []

    async def summarise(job, sections):
        events.append(("summary", job.section_id, [(s.id, s.items[0].body) for s in sections]))
        return SectionDraft(title="Agenda", items=[DraftItem(body="First and second.", priority=1)])

    _, path, writer, _, _ = build(tmp_path, text, events=events, doctype=doctype, summarise=summarise)
    assert sorted(writer.drafts) == ["one", "two"]
    assert sorted(events[:2]) == [("draft", "one"), ("draft", "two")]
    assert events[2:] == [("summary", "agenda", [("one", "First."), ("two", "Second.")])]
    doc, findings = parse(path.read_text())
    assert not [f for f in findings if f.severity == "error"]
    assert [item.body for item in doc.sections[0].items] == ["First and second."]
