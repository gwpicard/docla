# Intent: plan an outline from facts and turn accepted lines into a stamped document.
import asyncio
import importlib
import importlib.util
import json
import re

import pytest

from docla import doctypes, source
from docla.model import Document
from docla.render.compose import default_chooser
from docla.source.ids import IdStore
from docla.theme import neutral_theme


def optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        try:
            spec = importlib.util.find_spec(name)
        except ModuleNotFoundError as missing:
            if not name.startswith(f"{missing.name}."):
                raise
            spec = None
        if spec is not None:
            raise
        return None


planner = optional("docla.agents.planner")
client = optional("docla.agents.client")
fakes = optional("docla.testing.fakes")
prompts = optional("docla.agents.prompts")
gatherer = optional("docla.agents.gatherer")


class Ledger:
    def add(self, role, model, usage):
        pass


def need_planner():
    assert planner is not None, "docla.agents.planner must exist"
    for name in ("Outline", "OutlineLine", "OutlineRejected", "plan", "outline_to_document"):
        assert hasattr(planner, name), f"planner.{name} must exist"


def need_dependencies():
    for module, names in ((client, ("Claude",)), (fakes, ("FakeTransport", "fake_response")),
                          (prompts, ("system_blocks",)), (gatherer, ("Fact",))):
        assert module is not None, "planner dependency must exist"
        for name in names:
            assert hasattr(module, name), f"{module.__name__}.{name} must exist"


def reply(intent="statement", questions=None):
    return {"lines": [{"section": "opener", "title": "Catch drift early", "intent": intent,
                       "component": "Statement", "facts": ["F1"], "gap": None}],
            "questions": [] if questions is None else questions}


def setup_plan(replies):
    transport = fakes.FakeTransport({"claude-opus-5-5": [fakes.fake_response(json.dumps(item)) for item in replies]})
    claude = client.Claude(transport, Ledger(), {"planner": "claude-opus-5-5"})
    facts = [gatherer.Fact(text="Short intervals catch drift early.", source_key="S1", locator="00:41"),
             gatherer.Fact(text="Inspection intervals were set in 2019.", source_key="S2", locator="p.4")]
    return transport, claude, facts


def request_text(request):
    return "\n".join(block["text"] for block in request["messages"][0]["content"] if block["type"] == "text")


def test_D1_prompt_and_structured_reply():
    need_planner()
    need_dependencies()
    expected = reply()
    transport, claude, facts = setup_plan([expected])
    result = asyncio.run(planner.plan(claude, facts, doctypes.load_doctypes()["pitch-deck"], "BRIEF X"))
    assert isinstance(result, planner.Outline)
    assert result.model_dump() == expected
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["system"] == prompts.system_blocks("planner", neutral_theme(), "BRIEF X")
    text = request_text(request)
    assert "pitch-deck" in text
    assert "F1 [S1 00:41] Short intervals catch drift early." in text
    assert "F2 [S2 p.4] Inspection intervals were set in 2019." in text
    chooser = default_chooser()
    allowed = {intent for intent, fmt in chooser.entries if chooser.knows(intent, "slides")}
    assert {"statement", "bullets", "chronology"} <= allowed
    for intent in allowed:
        assert re.search(rf"(?m)^\s*{re.escape(intent)}:", text), intent


@pytest.mark.parametrize("unknown", ["timeline", "body"])
def test_D2_unknown_intent_retried_and_corrected(unknown):
    need_planner()
    need_dependencies()
    corrected = reply("bullets")
    transport, claude, facts = setup_plan([reply(unknown), corrected])
    result = asyncio.run(planner.plan(claude, facts, doctypes.load_doctypes()["pitch-deck"], "BRIEF X"))
    assert len(transport.requests) == 2
    assert unknown in request_text(transport.requests[1])
    assert result.model_dump() == corrected


@pytest.mark.parametrize("unknown", ["timeline", "body"])
def test_D2_unknown_intent_refused_after_retry(unknown):
    need_planner()
    need_dependencies()
    transport, claude, facts = setup_plan([reply(unknown), reply(unknown)])
    with pytest.raises(planner.OutlineRejected, match=unknown) as error:
        asyncio.run(planner.plan(claude, facts, doctypes.load_doctypes()["pitch-deck"], "BRIEF X"))
    assert isinstance(error.value, ValueError)
    assert len(transport.requests) == 2


def test_D3_questions_limited_and_line_metadata_preserved():
    need_planner()
    need_dependencies()
    response = reply(questions=["Who decides?", "When?", "What budget?"])
    response["lines"][0]["gap"] = "pilot cost"
    response["lines"][0]["facts"] = ["F2", "F1"]
    transport, claude, facts = setup_plan([response])
    result = asyncio.run(planner.plan(claude, facts, doctypes.load_doctypes()["pitch-deck"], "BRIEF X"))
    assert result.questions == ["Who decides?", "When?"]
    assert result.lines[0].gap == "pilot cost"
    assert result.lines[0].facts == ["F2", "F1"]
    assert len(transport.requests) == 1


def test_D4_document_stamping_and_round_trip(tmp_path):
    need_planner()
    outline = planner.Outline(lines=[
        planner.OutlineLine(section="opener", title="The case", intent="statement", component="Statement"),
        planner.OutlineLine(section="content", title="Pilot", intent="bullets", component="Bullet list", gap="pilot cost"),
        planner.OutlineLine(section="ask", title="Decision", intent="statement", component="Statement"),
    ])
    front = {"doctype": "pitch-deck", "format": "slides", "title": "Asset integrity"}
    store = IdStore(tmp_path / "ids.json")
    doc = planner.outline_to_document(outline, front, store=store)
    assert isinstance(doc, Document)
    assert doc.format == "slides"
    assert doc.front == {"doctype": "pitch-deck", "title": "Asset integrity"}
    expected = [("statement", "opener", "The case", []),
                ("bullets", "content", "Pilot", ["[GAP: pilot cost]"]),
                ("statement", "ask", "Decision", [])]

    def values(document):
        return [(s.intent, s.section, s.title, s.paragraphs) for s in document.sections]

    assert values(doc) == expected
    ids = [s.id for s in doc.sections]
    assert len(set(ids)) == 3
    assert all(isinstance(item, str) and re.fullmatch(r"[0-9a-f]{5}", item) for item in ids)
    assert set(ids) <= store.issued
    parsed = source.parse(source.serialise(doc))[0]
    assert [s.id for s in parsed.sections] == ids
    assert values(parsed) == expected
    unstored = planner.outline_to_document(outline, front)
    assert len({s.id for s in unstored.sections}) == 3
    assert all(s.id is not None and re.fullmatch(r"[0-9a-f]{5}", s.id) for s in unstored.sections)


@pytest.mark.parametrize("front", [{"title": "Asset integrity"}, {"format": "deck"}])
def test_D4_invalid_front_format_rejected(front):
    need_planner()
    with pytest.raises(ValueError):
        planner.outline_to_document(planner.Outline(lines=[]), front)
