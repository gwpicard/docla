# Intent: Write a reviewable outline and build the approved deck.
import asyncio
import importlib.util

from docla import cli
from docla.model import Citation, Document, Item, Section
from docla.source.parser import parse
from docla.theme import neutral_theme

try:
    import docla.write as write
except ImportError as error:
    if error.name != "docla.write" or importlib.util.find_spec("docla.write") is not None:
        raise
    write = None

FRONT = "---\ndoctype: pitch-deck\nformat: slides\ntitle: Readout\n---\n"
SLIDES = (
    FRONT
    + """
## Sources

- [S1] workshop.vtt, transcript

::: {#aaaa1 .section intent="statement"}
## One pilot is enough
:::

::: {#aaaa2 .section intent="bullets"}
## Why it works

- Short intervals catch drift early. [S1 00:41]
- Cheap to repeat.
:::
"""
)
DOC = """---
doctype: report
format: doc
title: Note
---

## Sources

- [S1] workshop.vtt, transcript

::: {#bbbb1 .section intent="body"}
## Findings

The pipeline drops some readings, and the team agreed to measure how many. [S1 00:41]
:::
"""


def need_write():
    assert write is not None, "docla.write must exist"
    assert hasattr(write, "Agents") and hasattr(write, "run_write")
    return write


def project(tmp_path):
    deck = tmp_path / "deck.md"
    deck.write_text(FRONT)
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "notes.txt").write_text("Cheap to repeat.\n")
    (sources / "brief.md").write_text("# Pilot\nOne pilot is enough.\n")
    (sources / "workshop.vtt").write_text(
        "WEBVTT\n\n00:00:41.000 --> 00:00:44.000\nShort intervals catch drift early.\n"
    )
    return deck


class FakeAgents:
    def __init__(self):
        self.gathers = []
        self.outlines = 0
        self.drafts = []

    async def gather(self, extracted):
        from docla.agents.gatherer import Fact

        self.gathers.append(extracted)
        return [
            Fact(text="Short intervals catch drift early.", source_key="S1", locator="00:41"),
            Fact(text="Cheap to repeat.", source_key="S1", locator="00:41"),
        ]

    async def outline(self, facts, doctype, front, store):
        self.outlines += 1
        return Document(
            front=front,
            format="slides",
            sections=[
                Section(intent="statement", title="One pilot is enough"),
                Section(intent="bullets", title="Why it works"),
            ],
        ), ["Who is the audience?"]

    def writer(self, facts, doc):
        self.doc = doc
        return self

    async def draft(self, job):
        self.drafts.append(job.section_id)
        # SectionJob.section is the outline slot name (M3.09); find the section by id.
        section = next(s for s in self.doc.sections if s.id == job.section_id).model_copy(deep=True)
        if section.intent == "bullets":
            section.items = [
                Item(body="Short intervals catch drift early.", citations=[Citation(key="S1", locator="00:41")]),
                Item(body="Cheap to repeat."),
            ]
        return section

    async def repair(self, job, state, history, *, strategy=None):
        raise AssertionError("clean sections should not require repair")

    def agents(self):
        return need_write().Agents(gather=self.gather, outline=self.outline, writer=self.writer)


def run(deck, fake, out, approve, **kwargs):
    return asyncio.run(
        need_write().run_write(deck, agents=fake.agents(), theme=neutral_theme(), out=out, approve=approve, **kwargs)
    )


def invoke(args, capsys):
    try:
        code = cli.main(args)
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_outline_is_saved_and_repeated_without_agents(tmp_path, capsys):
    need_write()
    deck = project(tmp_path)
    fake = FakeAgents()
    assert run(deck, fake, tmp_path / "out", False) == 0
    output = capsys.readouterr().out.splitlines()
    doc, findings = parse(deck.read_text())
    assert not [f for f in findings if f.severity == "error"]
    assert len(list((tmp_path / "extracted").iterdir())) == 3
    assert len(fake.gathers) == 1 and len(fake.gathers[0]) == 3
    assert (tmp_path / ".docla/write/deck/facts.json").is_file()
    assert [s.intent for s in doc.sections] == ["statement", "bullets"]
    assert all(s.id for s in doc.sections)
    assert [s.key for s in doc.sources] == ["S1", "S2", "S3"]
    assert all(any(line.startswith(f"{s.id} {s.intent} {s.title}") for line in output) for s in doc.sections)
    assert "question: Who is the audience?" in output
    assert output[-1] == f"approve the outline with: docla write {deck} --approve"
    assert fake.drafts == [] and fake.outlines == 1
    assert run(deck, fake, tmp_path / "out", False) == 0
    assert len(fake.gathers) == 1 and fake.outlines == 1 and fake.drafts == []
    assert capsys.readouterr().out.splitlines()[-1] == f"approve the outline with: docla write {deck} --approve"


def test_D2_approved_outline_drafts_patches_and_builds(tmp_path, capsys):
    need_write()
    deck = project(tmp_path)
    fake = FakeAgents()
    assert run(deck, fake, tmp_path / "out", False) == 0
    capsys.readouterr()
    doc, _ = parse(deck.read_text())
    assert run(deck, fake, tmp_path / "out", True) == 0
    output = capsys.readouterr().out.splitlines()
    assert len(fake.gathers) == 1
    assert sorted(fake.drafts) == sorted(s.id for s in doc.sections)
    for section in doc.sections:
        assert f"section {section.id}: clean; total cost $0.0000" in output
    pdf = tmp_path / "out/deck.pdf"
    assert pdf.is_file() and pdf.read_bytes().startswith(b"%PDF")
    assert str(pdf) in output
    assert len((tmp_path / ".docla/oplog.jsonl").read_text().splitlines()) == 2
    code, out, _ = invoke(["check", str(deck), "--out", str(tmp_path / "check")], capsys)
    assert code == 0 and out.splitlines() == ["no findings"]


def test_D3_large_outline_can_be_cancelled(tmp_path, capsys):
    need_write()
    deck = project(tmp_path)
    deck.write_text(
        FRONT + "\n" + "\n".join(f'::: {{#{i:05x} .section intent="statement"}}\n## Slide {i}\n:::' for i in range(41))
    )
    fake = FakeAgents()
    prompts = []

    def confirm(prompt):
        prompts.append(prompt)
        return "n"

    assert run(deck, fake, tmp_path / "out", True, confirm=confirm) == 1
    output = capsys.readouterr().out.splitlines()
    assert any(line.startswith("estimate: 41 sections") for line in output)
    assert "cancelled" in output
    assert prompts == ["continue? [y/N] "] and fake.drafts == []


def test_D4_replay_never_constructs_live_transport(tmp_path, monkeypatch, capsys):
    from docla.agents.cassette import CassetteMiss

    module = need_write()
    deck = project(tmp_path)
    calls = []

    def live():
        calls.append(True)

        def miss(*args, **kwargs):
            raise CassetteMiss("missing recording")

        return miss

    monkeypatch.setattr(module, "live_transport", live)
    monkeypatch.delenv("DOCLA_LIVE", raising=False)
    monkeypatch.delenv("DOCLA_RECORD", raising=False)
    code, _, err = invoke(["write", str(deck)], capsys)
    assert code == 2 and "DOCLA_LIVE=1" in err and "cassette.json" in err
    assert calls == []
    monkeypatch.setenv("DOCLA_LIVE", "1")
    code, _, _ = invoke(["write", str(deck)], capsys)
    assert code == 2 and calls == [True]


def test_D5_role_models_defaults_and_overrides(tmp_path):
    module = need_write()
    from docla.agents.prompts import ROLES
    from docla.config import ProjectConfig, load_project_config

    models = module.role_models(ProjectConfig())
    assert set(ROLES) <= set(models)
    assert [models[k] for k in ("gatherer", "writer.draft", "writer.repair", "planner")] == [
        "claude-sonnet-5-5",
        "claude-sonnet-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    ]
    (tmp_path / "docla.toml").write_text('[models]\nwriter = "w"\n"writer.repair" = "r"\n')
    models = module.role_models(load_project_config(tmp_path))
    assert [models[k] for k in ("writer.draft", "gatherer", "writer.repair")] == ["w", "w", "r"]


def test_D6_existing_clean_check_outputs(tmp_path, capsys):
    theme_slides = SLIDES.replace("- Cheap to repeat.", "- Cheap to repeat. [S1 00:41]\n- Easy to explain. [S1 00:41]")
    theme_doc = (
        DOC
        + '\n::: {#bbbb2 .section intent="callout"}\n## Note\n\nMeasure the dropped readings first. [S1 00:41]\n:::\n'
    )
    for i, text in enumerate((SLIDES, DOC, theme_slides, theme_doc)):
        path = tmp_path / f"input{i}.md"
        path.write_text(text)
        code, out, _ = invoke(["check", str(path), "--out", str(tmp_path / f"out{i}")], capsys)
        assert code == 0 and out.splitlines() == ["no findings"]
