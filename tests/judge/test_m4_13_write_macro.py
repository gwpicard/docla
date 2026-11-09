# Intent: Complete approved writing through the macro loop and its live adapters.
import asyncio
import importlib.util
import inspect
import json
import runpy
from pathlib import Path

from docla import cli
from docla.source.parser import parse
from docla.theme import neutral_theme

try:
    import docla.write as write
except ImportError as error:
    if error.name != "docla.write" or importlib.util.find_spec("docla.write") is not None:
        raise
    write = None

HERE = Path(__file__).parent
FROZEN = runpy.run_path(str(HERE / "test_m3_15_write_command.py"))


def need_write():
    assert write is not None and hasattr(write, "run_write") and hasattr(write, "Agents")
    return write


class FileWriter:
    def __init__(self):
        self.drafts = []

    async def gather(self, extracted):
        return []

    async def outline(self, *args):
        raise AssertionError("an approved outline must not be replanned")

    def writer(self, facts, doc):
        self.doc = doc
        return self

    async def draft(self, job):
        self.drafts.append(job.section_id)
        return next(s for s in self.doc.sections if s.id == job.section_id).model_copy(deep=True)

    async def repair(self, *args, **kwargs):
        raise AssertionError("clean sections must not be repaired")

    def agents(self, **kwargs):
        return need_write().Agents(gather=self.gather, outline=self.outline, writer=self.writer, **kwargs)


def seeded_deck(path):
    text = "---\ndoctype: pitch-deck\nformat: slides\ntitle: Readout\n---\n\n"
    text += "## Sources\n\n- [S1] workshop.vtt, transcript\n\n"
    text += '::: {#aaaa1 .section section="opener" intent="statement"}\n## One pilot is enough\n:::\n\n'
    for i in range(2, 6):
        text += f'::: {{#aaaa{i} .section section="content" intent="card-set"}}\n## Pilot benefits\n\n'
        text += "- Short intervals catch drift early. [S1 00:41]\n- Cheap to repeat. [S1 00:41]\n"
        text += "- Easy to explain. [S1 00:41]\n:::\n\n"
    text += '::: {#aaaa6 .section section="ask" intent="statement"}\n## Approve the pilot\n:::\n'
    path.write_text(text)


def test_D1_approved_deck_is_routed_and_versioned(tmp_path, capsys):
    module = need_write()
    deck = tmp_path / "deck.md"
    seeded_deck(deck)
    fake = FileWriter()
    out = tmp_path / "out"
    assert asyncio.run(module.run_write(deck, agents=fake.agents(), theme=neutral_theme(), out=out, approve=True)) == 0
    output = capsys.readouterr().out.splitlines()
    version = tmp_path / "deck.versions/v1"
    assert version.is_dir(), "approved writing must store a version"
    manifest = json.loads((version / "manifest.json").read_text())
    assert manifest["findings"]["error"] == 0
    assert manifest["findings"]["warning"] == 0
    assert manifest["residual"] == []
    composition = json.loads((version / "composition.json").read_text())
    components = [s["component"] for s in composition["sections"]]
    assert all(len(set(components[i : i + 3])) > 1 for i in range(len(components) - 2))
    assert (out / "deck.pdf").read_bytes() == (version / "deck.pdf").read_bytes()
    assert str(out / "deck.pdf") in output and str(version) in output
    doc, findings = parse(deck.read_text())
    assert not [f for f in findings if f.severity == "error"]
    assert any(
        s.intent == "card-set" and s.component == "bullets" and s.because.startswith("router: switched from cards")
        for s in doc.sections
    )
    lines = (tmp_path / ".docla/oplog.jsonl").read_text().splitlines()
    assert len(lines) == 7 and json.loads(lines[-1])["reason"] == "Macro loop"
    assert sorted(fake.drafts) == ["aaaa1", "aaaa2", "aaaa3", "aaaa4", "aaaa5", "aaaa6"]


def test_D2_page_critic_receives_composition(tmp_path):
    module = need_write()
    assert "critic" in inspect.signature(module.Agents).parameters, "Agents must accept a critic factory"
    deck = tmp_path / "deck.md"
    deck.write_text(FROZEN["SLIDES"])
    fake = FileWriter()
    pages = []

    async def critic(page):
        pages.append(page)
        return []

    assert (
        asyncio.run(
            module.run_write(
                deck,
                agents=fake.agents(critic=lambda doc: critic),
                theme=neutral_theme(),
                out=tmp_path / "out",
                approve=True,
            )
        )
        == 0
    )
    assert [p.page for p in pages] == [1, 2]
    assert [p.components for p in pages] == [{"aaaa1": "statement"}, {"aaaa2": "bullets"}]
    manifest = json.loads((tmp_path / "deck.versions/v1/manifest.json").read_text())
    assert manifest["look"]["tiers"]["semantic"] == "ok"


def test_D2_summary_is_written_after_drafts(tmp_path, monkeypatch):
    from docla.agents.writer import DraftItem, SectionDraft
    from docla.doctypes import load_doctype

    module = need_write()
    assert "summariser" in inspect.signature(module.Agents).parameters, "Agents must accept a summariser factory"
    doctype_path = tmp_path / "pitch-deck.yaml"
    doctype_path.write_text(
        "name: pitch-deck\nformat: slides\naudience: Readers\nlength: {slides: [2, 10]}\n"
        "questions: []\noutline:\n"
        "  - {section: content, intent: statement}\n"
        "  - {section: agenda, intent: bullets, fill: summary, from: [content]}\n"
        "checks: []\nchecklist: []\n"
    )
    monkeypatch.setattr(module, "load_doctypes", lambda: {"pitch-deck": load_doctype(doctype_path)})
    deck = tmp_path / "deck.md"
    deck.write_text(
        "---\ndoctype: pitch-deck\nformat: slides\ntitle: Readout\n---\n\n"
        '::: {#aaaa1 .section section="content" intent="statement"}\n## One pilot is enough\n:::\n\n'
        '::: {#aaaa2 .section section="agenda" intent="bullets"}\n## Agenda\n:::\n'
    )
    fake = FileWriter()
    calls = []

    async def summarise(job, sections):
        calls.append((job.section_id, list(fake.drafts)))
        return SectionDraft(title="Agenda", items=[DraftItem(body="One pilot is enough", priority=1)])

    assert (
        asyncio.run(
            module.run_write(
                deck,
                agents=fake.agents(summariser=lambda doc: summarise),
                theme=neutral_theme(),
                out=tmp_path / "out",
                approve=True,
            )
        )
        == 0
    )
    assert calls == [("aaaa2", ["aaaa1"])]
    doc, _ = parse(deck.read_text())
    assert [item.body for item in doc.sections[1].items] == ["One pilot is enough"]


def test_D3_critic_adapter_is_public():
    module = need_write()
    assert hasattr(module, "ClaudeCritic"), "docla.write.ClaudeCritic must exist"


def test_D4_agent_factories_are_available():
    module = need_write()
    agents = module.claude_agents(object(), neutral_theme())
    assert callable(getattr(agents, "critic", None))
    assert callable(getattr(agents, "summariser", None))


def test_D5_frozen_approved_write_and_replay(tmp_path, monkeypatch, capsys):
    (tmp_path / "approved").mkdir()
    (tmp_path / "replay").mkdir()
    FROZEN["test_D2_approved_outline_drafts_patches_and_builds"](tmp_path / "approved", capsys)
    FROZEN["test_D4_replay_never_constructs_live_transport"](tmp_path / "replay", monkeypatch, capsys)


def test_D6_frozen_clean_checks(tmp_path, capsys):
    for name in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        cases = runpy.run_path(str(HERE / name))
        for key in ("SLIDES", "DOC"):
            path = tmp_path / f"{name}-{key}.md"
            path.write_text(cases[key])
            assert cli.main(["check", str(path), "--out", str(tmp_path / f"out-{name}-{key}")]) == 0
            assert capsys.readouterr().out.splitlines() == ["no findings"]
