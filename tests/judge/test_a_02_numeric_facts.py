# Intent: Give facts stable identities and resolve report numbers to their supporting facts.
import inspect
import asyncio
import hashlib
import importlib
import importlib.util
import json
from datetime import date
from decimal import Decimal

from pydantic import TypeAdapter

from docla import doctypes
from docla.model import Document, Item, Section
from docla.theme import neutral_theme


def optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name or ""
        if (missing == name or name.startswith(missing + ".")) and importlib.util.find_spec(missing) is None:
            return None
        raise


gatherer = optional("docla.agents.gatherer")
tables = optional("docla.tables")
guards = optional("docla.loop.guards")
planner = optional("docla.agents.planner")
writer = optional("docla.agents.writer")
write = optional("docla.write")


def need(module, *names):
    assert module is not None, "public module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"


def workbook(tmp_path):
    assert importlib.util.find_spec("openpyxl") is not None, "openpyxl must be installed"
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sales"
    sheet.append(["Region", "Revenue", "Margin", "Date", "Deals", "Note"])
    sheet.append(["North", 1234500, 0.125, date(2024, 1, 15), 42, "Strong"])
    sheet.append(["South", 980000.5, None, None, 7, None])
    sheet["B2"].number_format = '"£"#,##0'
    sheet["C2"].number_format = "0.0%"
    sheet["B3"].number_format = "#,##0.00"
    path = tmp_path / "sales.xlsx"
    book.save(path)
    return path


def table_facts(tmp_path):
    need(tables, "table_facts")
    need(gatherer, "with_fact_ids")
    assert "typed" in inspect.signature(tables.table_facts).parameters, "docla.tables.table_facts must accept typed="
    return gatherer.with_fact_ids(tables.table_facts(workbook(tmp_path), "S1", typed=True))


def section(body, note=None):
    return Section(id="a1234", intent="bullets", title="North", items=[Item(body=body)], note=note)


def test_D1_fact_defaults_round_trip_and_gather(tmp_path):
    need(gatherer, "Fact", "gather")
    fact = gatherer.Fact(text="Revenue rose.", source_key="S2", locator="p.4")
    for name in ("id", "kind", "value", "unit"):
        assert hasattr(fact, name), f"Fact.{name} must exist"
    assert (fact.id, fact.kind, fact.value, fact.unit) == (None, "text", None, None)
    typed = gatherer.Fact(text="Revenue", source_key="S2", kind="currency", value=Decimal("1234500"), unit="GBP")
    adapter = TypeAdapter(list[gatherer.Fact])
    assert adapter.validate_json(adapter.dump_json([typed])) == [typed]
    sources = optional("docla.sources")
    need(sources, "Extracted")
    path = tmp_path / "source.txt"
    path.write_text("Revenue rose.")
    extracted = sources.Extracted(key="S1", name=path.name, kind="text", source=path, path=path, text="Revenue rose.")

    class Claude:
        async def cite(self, role, *, system, content):
            return {
                "content": [
                    {
                        "type": "text",
                        "citations": [{"type": "char_location", "cited_text": "Revenue rose.", "start_char_index": 0}],
                    }
                ]
            }

    assert asyncio.run(gatherer.gather(Claude(), [extracted])) == [
        gatherer.Fact(text="Revenue rose.", source_key="S1", locator=None)
    ]


def test_D2_table_cells_become_typed_facts(tmp_path):
    need(tables, "table_facts")
    assert "typed" in inspect.signature(tables.table_facts).parameters, "docla.tables.table_facts must accept typed="
    facts = tables.table_facts(workbook(tmp_path), "S1", typed=True)
    assert all(hasattr(f, "kind") and hasattr(f, "id") for f in facts), "typed Fact fields must exist"
    assert [(f.locator, f.kind, f.value, f.unit, f.id) for f in facts] == [
        ("Sales!B2", "currency", Decimal("1234500"), "GBP", None),
        ("Sales!C2", "percent", Decimal("12.5"), "%", None),
        ("Sales!D2", "date", None, None, None),
        ("Sales!E2", "number", Decimal("42"), None, None),
        ("Sales!F2", "text", None, None, None),
        ("Sales!B3", "number", Decimal("980000.5"), None, None),
        ("Sales!E3", "number", Decimal("7"), None, None),
    ]


def test_D3_ids_and_agent_prompts():
    need(gatherer, "Fact", "fact_id", "with_fact_ids")
    fact = gatherer.Fact(text="North, Revenue: £1,234,500", source_key="S1", locator="Sales!B2")
    expected = "F" + hashlib.sha256("S1\x1fSales!B2\x1fNorth, Revenue: £1,234,500".encode()).hexdigest()[:10]
    assert gatherer.fact_id(fact) == expected
    kept = gatherer.Fact(text="Other", source_key="S2", id="Fkeep")
    assigned = gatherer.with_fact_ids([fact, kept])
    assert [f.id for f in assigned] == [expected, "Fkeep"]
    assert fact.id is None and kept.id == "Fkeep"
    need(planner, "plan")
    need(writer, "draft", "SectionJob")
    client = optional("docla.agents.client")
    fakes = optional("docla.testing.fakes")
    need(client, "Claude")
    need(fakes, "FakeTransport", "fake_response")

    class Ledger:
        def add(self, role, model, usage):
            pass

    for identifier in ("Fx", None):
        sample = gatherer.Fact(
            text="Short intervals catch drift early.", source_key="S1", locator="00:41", id=identifier
        )
        reply = {
            "lines": [
                {
                    "section": "opener",
                    "title": "Catch drift early",
                    "intent": "statement",
                    "component": "Statement",
                    "facts": ["F1"],
                    "gap": None,
                }
            ],
            "questions": [],
        }
        transport = fakes.FakeTransport(
            {
                "p": [fakes.fake_response(json.dumps(reply))],
                "w": [fakes.fake_response(json.dumps({"title": "Title", "items": [], "paragraphs": []}))],
            }
        )
        claude = client.Claude(transport, Ledger(), {"planner": "p", "writer.draft": "w"})
        asyncio.run(planner.plan(claude, [sample], doctypes.load_doctypes()["pitch-deck"], "Brief"))
        job = writer.SectionJob(
            section_id="a1234",
            format="slides",
            intent="bullets",
            component="bullets",
            outline="Outline",
            section="content",
            audience="Team",
            purpose="Decide",
        )
        asyncio.run(writer.draft(claude, job, [sample], "Brief"))
        texts = [
            "\n".join(b["text"] for b in request["messages"][0]["content"] if b["type"] == "text")
            for request in transport.requests
        ]
        assert f"{identifier or 'F1'} [S1 00:41] Short intervals catch drift early." in texts[0]
        prefix = f"{identifier} " if identifier else ""
        assert prefix + '<source key="S1 00:41">Short intervals catch drift early.</source>' in texts[1]


def test_D4_resolve_and_guard_across_formats(tmp_path):
    need(guards, "resolve_numbers", "fact_number_tokens", "FactGuard")
    facts = table_facts(tmp_path)
    ids = {f.locator: f.id for f in facts}
    expected = {"1234500": [ids["Sales!B2"]], "12.5%": [ids["Sales!C2"]], "42": [ids["Sales!E2"]]}
    part = section("Revenue reached £1,234,500 at a 12.5% margin over 42 deals")
    assert guards.resolve_numbers(part, facts) == expected
    for fmt in ("slides", "doc"):
        doc = Document(front={}, format=fmt, sections=[part])
        guard = guards.FactGuard([], facts=facts)
        assert guard(doc, part) is True
        assert guard.unsupported == [] and guard.resolved == expected
    part.items[0].body = "Revenue reached £1,234,500 at a 13% margin over 42 deals"
    assert guard(doc, part) is False
    assert guard.unsupported == ["13%"] and guard.resolved["13%"] == []
    fact = gatherer.Fact(
        text="Units", source_key="S1", locator="Sales!B9", kind="number", value=Decimal("5000.00"), id="Fv"
    )
    assert guards.resolve_numbers(section("5000 units"), [fact]) == {"5000": ["Fv"]}


def test_D5_require_fact_ids_and_resolve_calculations(tmp_path):
    need(guards, "FactGuard")
    facts = table_facts(tmp_path)
    ids = {f.locator: f.id for f in facts}
    part = section("Revenue reached £1,234,500 across 50 sites")
    doc = Document(front={}, format="slides", sections=[part])
    strict = guards.FactGuard(["the target was 50 sites"], facts=facts, numbers_from_facts=True)
    assert strict(doc, part) is False and strict.unsupported == ["50"]
    relaxed = guards.FactGuard(["the target was 50 sites"], facts=facts)
    assert relaxed(doc, part) is True and relaxed.unsupported == []
    part = section("49 deals closed", note="calc: sum(42, 7) = 49")
    strict = guards.FactGuard([], facts=facts, numbers_from_facts=True)
    assert strict(doc, part) is True
    assert strict.resolved["49"] == sorted([ids["Sales!E2"], ids["Sales!E3"]])
    legacy = guards.FactGuard(["the pipeline drops 12% of readings"])
    assert legacy(doc, section("the pipeline drops 14% of readings")) is False
    assert legacy.unsupported == ["14%"]


def test_D6_write_saves_and_passes_ids(tmp_path):
    need(write, "run_write", "Agents")
    need(gatherer, "Fact", "fact_id")
    deck = tmp_path / "deck.md"
    deck.write_text("---\ndoctype: pitch-deck\nformat: slides\ntitle: Readout\n---\n")
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "notes.txt").write_text("Two findings.")

    class Agents:
        async def gather(self, extracted):
            return [
                gatherer.Fact(text="First fact.", source_key="S1"),
                gatherer.Fact(text="Second fact.", source_key="S1"),
            ]

        async def outline(self, facts, doctype, front, store):
            self.facts = facts
            return Document(
                front=front,
                format="slides",
                sections=[Section(intent="statement", title="First"), Section(intent="bullets", title="Second")],
            ), []

        def writer(self, facts, doc):
            raise AssertionError("unapproved outline must not draft")

    fake = Agents()
    agents = write.Agents(gather=fake.gather, outline=fake.outline, writer=fake.writer)
    assert (
        asyncio.run(write.run_write(deck, agents=agents, theme=neutral_theme(), out=tmp_path / "out", approve=False))
        == 0
    )
    saved = TypeAdapter(list[gatherer.Fact]).validate_json((tmp_path / ".docla/write/deck/facts.json").read_bytes())
    assert len(saved) == 2
    assert [f.id for f in saved] == [gatherer.fact_id(f) for f in saved]
    assert [f.id for f in fake.facts] == [f.id for f in saved]
