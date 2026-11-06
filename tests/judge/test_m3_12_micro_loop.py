# Intent: Draft, measure and repair one section until it clears or returns its least-bad residual.
import asyncio
import importlib.util
from dataclasses import dataclass
from pathlib import Path

from docla.checks.catalogue import all_rules
from docla.checks.engine import CheckContext, make_finding
from docla.model import Patch, PatchOp, Remedy
from docla.source.parser import parse
from docla.theme import neutral_theme

try:
    from docla.loop import micro
except ImportError as error:
    if error.name not in ("docla.loop", "docla.loop.micro"):
        raise
    if importlib.util.find_spec("docla.loop") is not None and importlib.util.find_spec("docla.loop.micro") is not None:
        raise
    micro = None

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/seeded-defects/geo.text-fits"


def interface():
    assert micro is not None, "docla.loop.micro must exist"
    for name in ("phi", "micro_rules", "edit_distance", "accept", "SectionState", "LoopContext", "write_section"):
        assert hasattr(micro, name), f"docla.loop.micro.{name} must exist"
    return micro


def fixture(side):
    doc, findings = parse((FIXTURES / side / "doc.md").read_text())
    assert not findings
    return doc, next(section for section in doc.sections if section.id == "c4e10")


@dataclass
class Job:
    section_id: str = "c4e10"
    format: str = "slides"


class Writer:
    def __init__(self, section, candidates):
        self.section = section
        self.candidates = candidates
        self.seen = []

    async def draft(self, job):
        return self.section

    async def repair(self, job, state, history, *, strategy=None):
        self.seen.append(state.section)
        items = self.candidates[min(len(self.seen) - 1, len(self.candidates) - 1)]
        return Patch(
            base_rev=0,
            author="ai",
            reason="repair",
            ops=[PatchOp(op="set_fields", section_id=job.section_id, fields={"items": items})],
        )


def run_loop(tmp_path, writer, **options):
    m = interface()
    doc, _ = fixture("fail")
    ctx = m.LoopContext(doc=doc, theme=neutral_theme(), workdir=tmp_path, writer=writer, **options)
    return asyncio.run(m.write_section(Job(), ctx))


def test_D1_scoring_filter_and_distance():
    m = interface()
    doc, section = fixture("fail")
    rules = all_rules()
    rule = next(r for r in rules if r.id == "geo.text-fits")
    findings = []
    for severity, remedy in [
        ("error", "redraft"),
        ("warning", "restructure"),
        ("info", "tune"),
        ("error", "engine"),
        ("error", "report"),
        ("error", "ask"),
    ]:
        r = rule.model_copy(update={"remedy": Remedy.model_validate({"class": remedy, "hint": "fix"})})
        findings.append(make_finding(r, CheckContext(doc), message="test", severity=severity))
    assert m.phi(findings) == 14
    filtered = m.micro_rules(rules)
    assert "geo.text-fits" in [r.id for r in filtered]
    assert "deck.no-component-three-running" not in [r.id for r in filtered]
    macro = next(r for r in rules if r.id == "deck.no-component-three-running")
    assert m.micro_rules([macro.model_copy(update={"loop": "micro"})])[0].id == macro.id
    changed = section.model_copy(deep=True)
    changed.items[0].body += " extra"
    assert m.edit_distance(section, section) == 0
    assert m.edit_distance(section, changed) > 0


def test_D2_acceptance():
    m = interface()
    _, section = fixture("fail")

    def state(score, fingerprints, error=None):
        return m.SectionState(
            section=section,
            findings=[],
            blocking=True,
            fingerprints=frozenset(fingerprints),
            phi=score,
            render=None,
            render_error=error,
            text_hash="hash",
            attempt=0,
            action="draft",
        )

    old = state(10, {"a"})
    assert m.accept(old, state(3, {"a"}), set(), section) is True
    assert m.accept(old, state(10, {"b"}), set(), section) is False
    assert m.accept(old, state(3, {"cleared"}), {"cleared"}, section) is False
    assert m.accept(old, state(0, set(), "compile failed"), set(), section) is False


def test_D3_repairs_overflow(tmp_path):
    _, section = fixture("fail")
    _, passing = fixture("pass")
    writer = Writer(section, [passing.items])
    result = run_loop(tmp_path, writer)
    assert result.status == "clean"
    assert result.attempts <= 3
    assert any(f.rule_id == "geo.text-fits" for f in result.history[0].findings)
    assert not any(f.rule_id == "geo.text-fits" for f in result.state.findings)
    assert len(writer.seen) == 1


def test_D4_rejects_worse_candidate(tmp_path):
    _, section = fixture("fail")
    _, passing = fixture("pass")
    worse = [item.model_copy(deep=True) for item in section.items]
    worse[0].body += " leverage"
    writer = Writer(section, [worse, passing.items])
    result = run_loop(tmp_path, writer)
    assert result.status == "clean"
    assert len(writer.seen) == 2
    assert writer.seen == [section, section]
    assert any(any(f.rule_id == "source.banned-terms" for f in s.findings) for s in result.history)


def test_D5_stall_and_residual(tmp_path):
    _, section = fixture("fail")
    candidates = []
    for word in ("updated", "altered"):
        items = [item.model_copy(deep=True) for item in section.items]
        items[0].body += " " + word
        candidates.append(items)
    calls = []

    async def hook(state, job, ctx, *, original):
        calls.append(original)
        return None

    writer = Writer(section, candidates)
    result = run_loop(tmp_path / "hook", writer, best_of_n=hook)
    assert result.status == "residual"
    assert calls == [section]
    assert len(writer.seen) <= 2
    writer = Writer(section, candidates)
    result = run_loop(tmp_path / "none", writer)
    assert result.status == "residual"
    assert result.state.phi == min(s.phi for s in result.history)


def test_D5_oscillation_calls_hook(tmp_path):
    _, section = fixture("fail")
    calls = []

    async def hook(state, job, ctx, *, original):
        calls.append(original)
        return None

    result = run_loop(tmp_path, Writer(section, [section.items]), best_of_n=hook)
    assert result.status == "residual"
    assert calls == [section]


def test_D6_lock_and_rejected_patch(tmp_path):
    _, section = fixture("fail")
    _, passing = fixture("pass")
    calls = []

    async def hook(state, job, ctx, *, original):
        calls.append(original)
        return None

    locked = section.model_copy(update={"lock": "text"})
    writer = Writer(locked, [])
    result = run_loop(tmp_path / "locked", writer, best_of_n=hook)
    assert result.status == "residual"
    assert writer.seen == []
    assert calls == []
    writer = Writer(section, [passing.items])
    result = run_loop(tmp_path / "guard", writer, micro_attempts=1, fact_guard=lambda doc, candidate: False)
    assert result.status == "residual"
    assert result.attempts == 1
    assert len(result.rejected) == 1 and "fact-unsupported" in result.rejected[0]
    assert result.state.section == section
