# Intent: Draft one cited, capacity-aware section and preserve its content in the working file.
import asyncio
import importlib
import importlib.util
import json

import pytest
from pydantic import ValidationError

from docla import source
from docla.model import Citation, Document, Item, Section, Source
from docla.render.components import all_manifests
from docla.theme import neutral_theme


def optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name or ""
        if (missing == name or name.startswith(missing + ".")) and importlib.util.find_spec(missing) is None:
            return None
        raise


writer = optional("docla.agents.writer")
client = optional("docla.agents.client")
fakes = optional("docla.testing.fakes")
gatherer = optional("docla.agents.gatherer")
prompts = optional("docla.agents.prompts")


def need(module, *names):
    assert module is not None, "required public module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"


class Ledger:
    def __init__(self):
        self.entries = []

    def add(self, role, model, usage):
        self.entries.append((role, model, usage))


def job(component="bullets"):
    return writer.SectionJob(section_id="a7c31", format="slides", intent="bullets", component=component,
                             outline="What the workshop found", section="content", audience="Engineers",
                             purpose="Agree a pilot")


def sample_draft():
    return writer.SectionDraft.model_validate({
        "title": "Why it works",
        "items": [
            {"head": "Intervals", "body": "catch drift early.", "priority": 2,
             "citations": [{"key": "S1", "locator": "00:41"}]},
            {"body": "Pilot cost [GAP: pilot cost]", "priority": 1},
        ],
        "paragraphs": ["[GAP: owner of the splash zone]"],
    })


def test_D1_draft_request_and_structured_reply():
    need(writer, "SectionJob", "SectionDraft", "draft")
    need(client, "Claude")
    need(fakes, "FakeTransport", "fake_response")
    need(gatherer, "Fact")
    need(prompts, "system_blocks")
    reply = {"title": "Why it works", "items": [
        {"head": "Intervals", "body": "catch drift early.", "priority": 2,
         "citations": [{"key": "S1", "locator": "00:41"}]},
        {"head": None, "body": "Pilot cost [GAP: pilot cost]", "priority": 1, "citations": []},
    ], "paragraphs": []}
    transport = fakes.FakeTransport({"claude-sonnet-5-5": [fakes.fake_response(json.dumps(reply))]})
    claude = client.Claude(transport, Ledger(), {"writer.draft": "claude-sonnet-5-5"})
    facts = [gatherer.Fact(text="Short intervals catch drift early.", source_key="S1", locator="00:41"),
             gatherer.Fact(text="Workshop notes.", source_key="S2", locator=None)]
    result = asyncio.run(writer.draft(claude, job(), facts, "BRIEF X", "EXEMPLAR TEXT 7"))
    assert isinstance(result, writer.SectionDraft)
    assert result.model_dump() == reply
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request["model"] == "claude-sonnet-5-5"
    assert request["system"] == prompts.system_blocks("writer.draft", neutral_theme(), "BRIEF X")
    assert request["output_config"]["effort"] == "medium"
    text = "\n".join(block["text"] for block in request["messages"][0]["content"] if block["type"] == "text")
    for expected in (all_manifests()["bullets"].capacity_text(), "Bullet list", "What the workshop found",
                     "slides", "Engineers", "Agree a pilot", "bullets", "EXEMPLAR TEXT 7", "[GAP:",
                     '<source key="S1 00:41">Short intervals catch drift early.</source>',
                     '<source key="S2">Workshop notes.</source>'):
        assert expected in text
    assert text.index('<source key="S1 00:41">') < text.index('<source key="S2">')


def test_D2_unknown_component_and_invalid_priority():
    need(writer, "SectionJob", "SectionDraft", "draft")
    need(client, "Claude")
    need(fakes, "FakeTransport", "fake_response")
    transport = fakes.FakeTransport({"claude-sonnet-5-5": [fakes.fake_response('{}')]})
    claude = client.Claude(transport, Ledger(), {"writer.draft": "claude-sonnet-5-5"})
    with pytest.raises(ValueError, match="missing-component"):
        asyncio.run(writer.draft(claude, job("missing-component"), [], "BRIEF X"))
    assert transport.requests == []
    with pytest.raises(ValidationError):
        writer.SectionDraft.model_validate({"items": [{"body": "A", "priority": 0}]})
    assert writer.SectionDraft.model_validate({"items": [{"body": "A", "priority": 1}]}).items[0].priority == 1


def test_D3_conversion_preserves_content_and_order():
    need(writer, "SectionJob", "SectionDraft", "draft_to_section")
    section = writer.draft_to_section(sample_draft(), job())
    assert isinstance(section, Section)
    assert (section.id, section.intent, section.section, section.title) == (
        "a7c31", "bullets", "content", "Why it works")
    assert section.component is None and section.owner is None
    assert section.items == [Item(head="Intervals", body="catch drift early.",
                                  citations=[Citation(key="S1", locator="00:41")]),
                             Item(body="Pilot cost [GAP: pilot cost]")]
    assert section.paragraphs == ["[GAP: owner of the splash zone]"]


def test_D4_converted_section_round_trips_in_working_file():
    need(writer, "SectionJob", "SectionDraft", "draft_to_section")
    section = writer.draft_to_section(sample_draft(), job())
    doc = Document(front={"title": "Workshop"}, format="slides",
                   sources=[Source(key="S1", text="workshop.vtt, transcript")], sections=[section])
    text = source.serialise(doc)
    assert "## Sources" in text and "[S1] workshop.vtt, transcript" in text
    parsed, findings = source.parse(text)
    assert not [finding for finding in findings if finding.severity == "error"]
    assert len(parsed.sections) == 1
    result = parsed.sections[0]
    assert result.title == "Why it works"
    assert [(item.head, item.body) for item in result.items] == [
        ("Intervals", "catch drift early."), (None, "Pilot cost [GAP: pilot cost]")]
    assert result.items[0].citations == [Citation(key="S1", locator="00:41")]
    assert result.paragraphs == ["[GAP: owner of the splash zone]"]
