# Intent: best-of-N renders different repairs and selects the best actionable, fact-preserving candidate.
import asyncio
import importlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path

from docla.model import Citation, Finding, Item, Patch, PatchOp, Remedy, Section
from docla.source.parser import parse
from docla.theme import neutral_theme


def _optional(name):
    parts = name.split(".")
    for end in range(1, len(parts) + 1):
        if importlib.util.find_spec(".".join(parts[:end])) is None:
            return None
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name == name or str(error.name).startswith(name + "."):
            return None
        raise


best = _optional("docla.loop.best_of")
micro = _optional("docla.loop.micro")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/seeded-defects/geo.text-fits"


def _require():
    assert best is not None, "docla.loop.best_of must exist"
    assert all(hasattr(best, name) for name in ("STRATEGIES", "score", "fact_preservation", "best_of_n"))
    assert micro is not None, "docla.loop.micro must exist"
    assert all(hasattr(micro, name) for name in ("SectionState", "LoopContext", "evaluate", "write_section"))


def _finding(severity, remedy="redraft"):
    return Finding(
        id="f",
        rule_id="r",
        tier="source",
        severity=severity,
        format="slides",
        section_id="s",
        message="finding",
        fingerprint="f",
        remedy=Remedy(class_=remedy, hint="fix"),
    )


def _state(section, findings=(), render_error=None):
    return micro.SectionState(
        section=section,
        findings=list(findings),
        blocking=False,
        fingerprints=frozenset(),
        phi=0,
        render=None,
        render_error=render_error,
        text_hash="",
        attempt=0,
        action="draft",
    )


def test_D1_score_priorities_and_fact_preservation():
    _require()
    assert len(best.STRATEGIES) == 3
    assert all(isinstance(s, str) and s.strip() for s in best.STRATEGIES)
    assert len(set(best.STRATEGIES)) == 3
    original = Section(id="s", intent="bullets", items=[Item(body="In 2019 there were 14 sites.")])
    dropped = original.model_copy(update={"items": [Item(body="There were 14 sites.")]})
    longer = original.model_copy(update={"items": [Item(body="In 2019 there were 14 sites, all inspected.")]})
    assert best.fact_preservation(original, original) == 1.0
    assert best.fact_preservation(original, dropped) == 0.5
    assert best.fact_preservation(Section(intent="body"), Section(intent="body")) == 1.0
    clean, lost, edited = (_state(s) for s in (original, dropped, longer))
    assert best.score(clean, original) == (0, 0, -1.0, 0)
    assert best.score(edited, original) < best.score(lost, original)
    assert best.score(clean, original) < best.score(edited, original)
    warning = _state(original, [_finding("warning")])
    error = _state(original, [_finding("error")])
    assert best.score(lost, original) < best.score(warning, original) < best.score(error, original)
    assert best.score(_state(original, [_finding("error", "report")]), original) == (0, 0, -1.0, 0)
    assert best.score(_state(original, render_error="failed"), original) > best.score(error, original)


@dataclass
class Job:
    section_id: str = "c4e10"
    format: str = "slides"


def _documents():
    fail, _ = parse((FIXTURES / "fail/doc.md").read_text(encoding="utf-8"))
    passed, _ = parse((FIXTURES / "pass/doc.md").read_text(encoding="utf-8"))
    return fail, next(s for s in fail.sections if s.id == "c4e10"), next(s for s in passed.sections if s.id == "c4e10")


class Writer:
    def __init__(self, initial, candidates):
        self.initial = initial
        self.candidates = candidates
        self.strategies = []
        self.loop_calls = 0

    async def draft(self, job):
        return self.initial

    async def repair(self, job, state, history, *, strategy=None):
        if strategy is None:
            self.loop_calls += 1
            items = list(state.section.items)
            items[0] = items[0].model_copy(update={"body": items[0].body + " clearly"})
        else:
            self.strategies.append(strategy)
            items = self.candidates[best.STRATEGIES.index(strategy)]
        return Patch(
            base_rev=0,
            author="ai",
            reason="repair",
            ops=[PatchOp(op="set_fields", section_id=job.section_id, fields={"items": items})],
        )


def _setup(tmp_path, candidates, guard=None):
    doc, original, passed = _documents()
    writer = Writer(original, candidates(original, passed))
    ctx = micro.LoopContext(doc=doc, theme=neutral_theme(), workdir=tmp_path, writer=writer, fact_guard=guard)
    job = Job()
    state = asyncio.run(micro.evaluate(original, job, ctx, tag="initial"))
    assert state.render_error is None
    assert any(f.rule_id == "geo.text-fits" for f in state.findings)
    return job, ctx, state, writer


def test_D2_picks_clear_candidate_and_renders_separately(tmp_path):
    _require()
    job, ctx, state, writer = _setup(
        tmp_path,
        lambda original, passed: [original.items, passed.items, passed.items + [Item(head="Extra", body="Short.")]],
    )
    result = asyncio.run(best.best_of_n(state, job, ctx, n=3))
    assert result is not None
    assert result.section.items == _documents()[2].items
    assert not any(f.rule_id == "geo.text-fits" for f in result.findings)
    assert writer.strategies == best.STRATEGIES
    assert all((tmp_path / f"c4e10-best-{k}").is_dir() for k in range(3)) or all(
        (tmp_path / f"c4e10-best-{k}").is_dir() for k in range(1, 4)
    )


def test_D3_preserves_fact_before_minimising_edits(tmp_path):
    _require()

    def candidates(original, passed):
        items = [item.model_copy(deep=True) for item in passed.items]
        items[0].citations = [Citation(key="S1", locator="00:41")]
        lost = [item.model_copy(deep=True) for item in items]
        lost[0].body = lost[0].body.replace("2019", "")
        kept = [item.model_copy(deep=True) for item in items]
        kept[2].body = "remain fragmented across locations, with limited visibility for the wider organisation."
        return [lost, kept]

    job, ctx, state, writer = _setup(tmp_path, candidates)
    result = asyncio.run(best.best_of_n(state, job, ctx, n=2))
    assert result is not None
    assert result.section.items == writer.candidates[1]
    assert not any(f.rule_id in {"geo.text-fits", "source.uncited-figure"} for f in result.findings)
    assert micro.edit_distance(state.section, result.section) > micro.edit_distance(
        state.section, state.section.model_copy(update={"items": writer.candidates[0]})
    )


def test_D4_rejected_patches_return_none(tmp_path):
    _require()
    job, ctx, state, writer = _setup(
        tmp_path, lambda original, passed: [passed.items, passed.items], guard=lambda doc, section: False
    )
    assert asyncio.run(best.best_of_n(state, job, ctx, n=2)) is None
    assert writer.strategies == best.STRATEGIES[:2]


def test_D5_write_section_calls_best_of_n_on_stall(tmp_path):
    _require()
    doc, original, passed = _documents()
    writer = Writer(original, [original.items, passed.items, passed.items + [Item(head="Extra", body="Short.")]])
    ctx = micro.LoopContext(doc=doc, theme=neutral_theme(), workdir=tmp_path, writer=writer, best_of_n=best.best_of_n)
    result = asyncio.run(micro.write_section(Job(), ctx))
    assert writer.loop_calls >= 1
    assert writer.strategies == best.STRATEGIES
    assert result.status == "clean"
    assert result.state.action == "best-of-n"
    assert result.state.section.items == passed.items
