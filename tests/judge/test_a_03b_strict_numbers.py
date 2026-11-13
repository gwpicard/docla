# Intent: Resolve spreadsheet numbers to facts while exempting document metadata.
import asyncio
import importlib.util
import inspect

import openpyxl
import pytest

from docla.agents import gatherer
from docla.model import Citation, Document, Item, Section, Source
from docla.tables import table_facts
from docla.theme import neutral_theme

try:
    import docla.loop.guards as guards
except ImportError as error:
    if error.name != "docla.loop.guards" or importlib.util.find_spec("docla.loop.guards") is not None:
        raise
    guards = None

try:
    import docla.write as write
except ImportError as error:
    if error.name != "docla.write" or importlib.util.find_spec("docla.write") is not None:
        raise
    write = None


def workbook(path):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sales"
    sheet.append(["Region", "Revenue"])
    sheet.append(["North", "£1,234,500"])
    book.save(path)
    book.close()


def facts_for(path):
    assert hasattr(gatherer, "with_fact_ids"), "with_fact_ids must exist"
    facts = gatherer.with_fact_ids(table_facts(path, "S1"))
    assert len(facts) == 1 and facts[0].id is not None
    return facts


def factory():
    assert write is not None and hasattr(write, "fact_guard_for"), "docla.write.fact_guard_for must exist"
    return write.fact_guard_for


def document(format="slides", title="Outlook to 2031"):
    return Document(front={"title": title}, format=format, sources=[Source(key="S1", text="sales.xlsx")])


def section(body, title="North by 2031"):
    return Section(id="aaaa1", intent="bullets", title=title, items=[Item(body=body)])


def test_D1_exemption_requires_plain_evidence(tmp_path):
    assert guards is not None and hasattr(guards, "FactGuard"), "FactGuard must exist"
    parameters = inspect.signature(guards.FactGuard).parameters
    assert {"facts", "numbers_from_facts", "exempt"} <= set(parameters), "FactGuard must support strict exemptions"
    path = tmp_path / "sales.xlsx"
    workbook(path)
    facts = facts_for(path)
    doc = document()
    item = section("Revenue reached £1,234,500 across 50 sites", title="Revenue")
    for evidence, strict, exempt, expected, unsupported in [
        (["50 sites"], True, {"50"}, True, []),
        (["50 sites"], True, set(), False, ["50"]),
        ([], True, {"50"}, False, ["50"]),
        (["50 sites"], False, {"50"}, True, []),
    ]:
        guard = guards.FactGuard(evidence, facts=facts, numbers_from_facts=strict, exempt=exempt)
        assert guard(doc, item) is expected
        assert guard.unsupported == unsupported


@pytest.mark.parametrize("format", ["slides", "doc"])
def test_D2_table_facts_exempt_front_matter_but_not_other_numbers(tmp_path, format):
    make_guard = factory()
    path = tmp_path / "sales.xlsx"
    workbook(path)
    facts = facts_for(path)
    doc = document(format)
    guard = make_guard(doc, facts)
    assert guard(doc, section("Revenue reached £1,234,500")) is True
    assert guard.unsupported == []
    assert guard(doc, section("Revenue reached £1,234,500 across 50 sites")) is False
    assert guard.unsupported == ["50"]


def test_D3_text_facts_keep_the_lenient_guard():
    make_guard = factory()
    doc = document(title="Outlook to 2026")
    facts = [gatherer.Fact(text="Most sites report weekly.", source_key="S1", locator="p.2")]
    guard = make_guard(doc, facts)
    assert guard(doc, section("Most sites report weekly in 2026", title="Report")) is True
    assert guard.unsupported == []
    assert guard(doc, section("the pipeline drops 14% of readings", title="Report")) is False
    assert guard.unsupported == ["14%"]


def test_D4_run_write_uses_factory_with_gathered_fact_ids(tmp_path, monkeypatch):
    make_guard = factory()
    sources = tmp_path / "sources"
    sources.mkdir()
    path = sources / "sales.xlsx"
    workbook(path)
    facts = facts_for(path)
    deck = tmp_path / "deck.md"
    deck.write_text("""---
doctype: pitch-deck
format: slides
title: Readout
---

## Sources

- [S1] sales.xlsx

::: {#aaaa1 .section intent="statement"}
## Revenue
:::

::: {#aaaa2 .section intent="bullets"}
## Results
:::
""")
    calls = []

    def record(doc, received):
        guard = make_guard(doc, received)
        calls.append((doc, list(received), guard))
        return guard

    monkeypatch.setattr(write, "fact_guard_for", record)

    class FakeAgents:
        async def gather(self, extracted):
            return table_facts(path, "S1")

        async def outline(self, facts, doctype, front, store):
            raise AssertionError("an approved outline must not be regenerated")

        def writer(self, facts, doc):
            self.doc = doc
            return self

        async def draft(self, job):
            result = next(s for s in self.doc.sections if s.id == job.section_id).model_copy(deep=True)
            if result.intent == "bullets":
                result.items = [
                    Item(body="Revenue reached £1,234,500.", citations=[Citation(key="S1", locator="Sales!B2")]),
                    Item(body="Revenue is reported for North.", citations=[Citation(key="S1", locator="Sales!B2")]),
                ]
            return result

        async def repair(self, job, state, history, *, strategy=None):
            raise AssertionError("clean sections should not require repair")

    fake = FakeAgents()
    agents = write.Agents(gather=fake.gather, outline=fake.outline, writer=fake.writer)
    result = asyncio.run(
        write.run_write(deck, agents=agents, theme=neutral_theme(), out=tmp_path / "out", approve=True)
    )
    assert result == 0
    assert len(calls) == 1
    doc, received, guard = calls[0]
    assert [source.key for source in doc.sources] == ["S1"]
    assert received == facts
    assert [fact.id for fact in received] == [gatherer.fact_id(fact) for fact in facts]
    assert guard(doc, section("Revenue reached £1,234,500 across 50 sites", title="Revenue")) is False
    assert guard.unsupported == ["50"]
