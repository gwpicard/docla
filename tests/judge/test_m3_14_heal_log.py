# Intent: Record healing attempts and resume finished sections without writer calls.
import asyncio
import importlib
import importlib.util
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from docla.model import Patch, PatchOp
from docla.source.parser import parse
from docla.theme import neutral_theme


def optional_module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name not in ("docla.loop", name):
            raise
        if importlib.util.find_spec("docla.loop") is not None and importlib.util.find_spec(name) is not None:
            raise
        return None


heal_log = optional_module("docla.loop.heal_log")
micro = optional_module("docla.loop.micro")

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/seeded-defects/geo.text-fits"
CLOCK = datetime(2026, 8, 28, 12, 34, 56, tzinfo=UTC)


def interface():
    assert heal_log is not None, "docla.loop.heal_log must exist"
    assert micro is not None, "docla.loop.micro must exist"
    for name in ("HealEntry", "HealLog", "resume"):
        assert hasattr(heal_log, name), f"docla.loop.heal_log.{name} must exist"
    for name in ("LoopContext", "write_section"):
        assert hasattr(micro, name), f"docla.loop.micro.{name} must exist"
    return heal_log, micro


def fixture(side):
    doc, findings = parse((FIXTURES / side / "doc.md").read_text())
    assert not findings
    return doc, next(section for section in doc.sections if section.id == "c4e10")


@dataclass
class Job:
    section_id: str = "c4e10"
    format: str = "slides"


class Writer:
    def __init__(self, section, items, fail_id=None):
        self.section = section
        self.items = items
        self.fail_id = fail_id
        self.drafts = 0
        self.repairs = 0

    async def draft(self, job):
        self.drafts += 1
        return self.section.model_copy(update={"id": job.section_id}, deep=True)

    async def repair(self, job, state, history, *, strategy=None):
        self.repairs += 1
        if job.section_id == self.fail_id:
            raise RuntimeError("killed run")
        return Patch(
            base_rev=0,
            author="ai",
            reason="repair overflow",
            ops=[PatchOp(op="set_fields", section_id=job.section_id, fields={"items": self.items})],
        )


def context(tmp_path, doc, writer, log):
    assert micro is not None, "docla.loop.micro must exist"
    return micro.LoopContext(doc=doc, theme=neutral_theme(), workdir=tmp_path, writer=writer, heal_log=log)


def completed(tmp_path):
    h, m = interface()
    doc, section = fixture("fail")
    _, passing = fixture("pass")
    writer = Writer(section, passing.items)
    log = h.HealLog(tmp_path, now=lambda: CLOCK)
    result = asyncio.run(m.write_section(Job(), context(tmp_path, doc, writer, log)))
    return result, passing, writer


def lines(tmp_path):
    return [json.loads(line) for line in (tmp_path / "heal.jsonl").read_text().splitlines()]


def test_D1_lines_validate_and_identify_scope_and_time(tmp_path):
    h, _ = interface()
    completed(tmp_path)
    entries = lines(tmp_path)
    assert entries
    for entry in entries:
        h.HealEntry.model_validate(entry)
        assert {
            "t",
            "scope",
            "attempt",
            "findings_before",
            "action",
            "patch_id",
            "findings_after",
            "phi",
            "cost_usd",
            "images",
        } <= entry.keys()
        assert entry["t"] == "2026-08-28T12:34:56Z"
        assert entry["scope"] == "section:c4e10"


def test_D2_repair_findings_crops_and_finished_section(tmp_path):
    result, passing, _ = completed(tmp_path)
    entries = lines(tmp_path)
    attempt = next(entry for entry in entries if entry["attempt"] == 1 and entry["action"] == "redraft")
    finding = next(f.id for f in result.history[0].findings if f.rule_id == "geo.text-fits")
    assert finding in attempt["findings_before"]
    assert finding not in attempt["findings_after"]
    assert attempt["phi"][1] < attempt["phi"][0]
    for side in ("before", "after"):
        path = Path(attempt["images"][side])
        assert not path.is_absolute()
        assert path.suffix == ".png"
        assert (tmp_path / path).resolve().is_relative_to(tmp_path.resolve())
        assert (tmp_path / path).is_file()
    assert entries[-1]["action"] == "clean"
    assert entries[-1]["status"] == "clean"
    assert entries[-1]["section"]["items"] == [item.model_dump(mode="json") for item in passing.items]


def test_D3_resume_ignores_missing_and_truncated_log(tmp_path):
    h, _ = interface()
    assert h.resume(tmp_path / "missing") == set()
    completed(tmp_path)
    assert h.resume(tmp_path) == {"c4e10"}
    with (tmp_path / "heal.jsonl").open("a") as stream:
        stream.write('{"scope":"section:unfinished"')
    assert h.resume(tmp_path) == {"c4e10"}


def test_D4_resume_skips_finished_writer_calls(tmp_path):
    h, m = interface()
    doc, section = fixture("fail")
    _, passing = fixture("pass")
    second = section.model_copy(update={"id": "second"}, deep=True)
    doc = doc.model_copy(update={"sections": [section, second]}, deep=True)
    writer = Writer(section, passing.items, fail_id="second")
    ctx = context(tmp_path, doc, writer, h.HealLog(tmp_path, now=lambda: CLOCK))
    first = asyncio.run(m.write_section(Job(), ctx))
    assert first.status == "clean"
    with pytest.raises(RuntimeError, match="killed run"):
        asyncio.run(m.write_section(Job("second"), ctx))
    assert h.resume(tmp_path) == {"c4e10"}
    before = (tmp_path / "heal.jsonl").read_bytes()
    fresh = Writer(section, passing.items)
    resumed = context(tmp_path, doc, fresh, h.HealLog(tmp_path, now=lambda: CLOCK))
    result = asyncio.run(m.write_section(Job(), resumed))
    assert (fresh.drafts, fresh.repairs) == (0, 0)
    assert result.status == "clean"
    assert result.state.section.items == passing.items
    assert (tmp_path / "heal.jsonl").read_bytes() == before
    asyncio.run(m.write_section(Job("second"), resumed))
    assert fresh.drafts == 1


def test_D5_without_log_preserves_micro_loop(tmp_path):
    assert micro is not None, "docla.loop.micro must exist"
    assert hasattr(micro, "write_section"), "docla.loop.micro.write_section must exist"
    doc, section = fixture("fail")
    _, passing = fixture("pass")
    writer = Writer(section, passing.items)
    result = asyncio.run(micro.write_section(Job(), context(tmp_path, doc, writer, None)))
    assert result.status == "clean"
    assert writer.repairs == 1


def test_D3_resume_survives_a_cut_multibyte_line_and_appends_after_it(tmp_path):
    h, _ = interface()
    log = tmp_path / "heal.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    # A run killed in the middle of a multibyte character leaves invalid UTF-8 at the end.
    log.write_bytes('{"scope":"section:other","note":"caf'.encode() + "é".encode()[:1])

    def resumed():
        try:
            return h.resume(tmp_path)
        except UnicodeDecodeError as error:
            raise AssertionError(f"resume must skip a cut multibyte line: {error}") from error

    assert resumed() == set()
    # A later run appends after the fragment; its finish line must still be read.
    completed(tmp_path)
    assert resumed() == {"c4e10"}
