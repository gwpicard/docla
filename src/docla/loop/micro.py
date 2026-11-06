"""Draft and measure a section until its blocking findings clear."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from docla.checks.catalogue import all_rules
from docla.checks.engine import TIERS, CheckContext, run_checks
from docla.loop.router import ACTIONABLE, deterministic_fix, route
from docla.model import Document, Finding, Format, Patch, Rule, Section
from docla.render.compose import ComposeError, compose
from docla.render.kit import read_tokens
from docla.render.swatch import SwatchRender, swatch
from docla.render.typst import TypstError
from docla.source.patches import FactGuard, PatchRejected, apply_patch
from docla.theme import Theme

if TYPE_CHECKING:
    from docla.loop.heal_log import HealLog


class JobLike(Protocol):
    section_id: str
    format: Format


class SectionWriter(Protocol):
    async def draft(self, job: JobLike) -> Section: ...

    async def repair(
        self, job: JobLike, state: SectionState, history: list[SectionState], *, strategy: str | None = None
    ) -> Patch: ...


@dataclass
class SectionState:
    section: Section
    findings: list[Finding]
    blocking: bool
    fingerprints: frozenset[str]
    phi: int
    render: SwatchRender | None
    render_error: str | None
    text_hash: str
    attempt: int
    action: str


BestOfN = Callable[..., Awaitable[SectionState | None]]


@dataclass
class LoopContext:
    doc: Document
    theme: Theme
    workdir: Path
    writer: SectionWriter
    rules: list[Rule] = field(default_factory=all_rules)
    assets: list[Path] | None = None
    fact_guard: FactGuard | None = None
    micro_attempts: int = 3
    best_of_n: BestOfN | None = None
    blocking_severities: frozenset[str] = frozenset({"error"})
    final: bool = False
    heal_log: HealLog | None = None
    spent: Callable[[], float] | None = None
    _logged_spent: float = field(default=0.0, init=False, repr=False)


def micro_rules(rules: list[Rule]) -> list[Rule]:
    return [rule for rule in rules if rule.loop in ("micro", "both")]


def phi(findings: list[Finding]) -> int:
    weights = {"error": 10, "warning": 3, "info": 1}
    return sum(weights[f.severity] for f in findings if f.remedy.class_ in ACTIONABLE)


def _text(section: Section) -> str:
    return "\n".join(
        [
            section.title or "",
            *(part for item in section.items for part in (item.head or "", item.body)),
            *section.paragraphs,
        ]
    )


def edit_distance(a: Section, b: Section) -> int:
    return sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, _text(a), _text(b), autojunk=False).get_opcodes()
        if tag != "equal"
    )


async def evaluate(
    section: Section, job: JobLike, ctx: LoopContext, *, tag: str, attempt: int = 0, action: str = "draft"
) -> SectionState:
    doc = ctx.doc.model_copy(update={"sections": [section]})
    render = None
    error = None
    try:
        render = await asyncio.to_thread(swatch, doc, job.section_id, ctx.workdir / tag, ctx.theme, assets=ctx.assets)
        check_ctx = CheckContext(
            doc,
            render.facts,
            read_tokens(render.main.parent),
            theme=ctx.theme,
            composition=compose(doc, assets=ctx.assets),
            final=ctx.final,
            assets=ctx.assets,
        )
    except (ComposeError, TypstError) as exc:
        error = str(exc)
        render = None
        check_ctx = CheckContext(doc, theme=ctx.theme, final=ctx.final, assets=ctx.assets)
    rules = micro_rules(ctx.rules)
    findings = [
        finding for tier in TIERS for finding in run_checks([rule for rule in rules if rule.tier == tier], check_ctx)
    ]
    actionable = [f for f in findings if f.remedy.class_ in ACTIONABLE]
    return SectionState(
        section,
        findings,
        bool(error is not None or any(f.severity in ctx.blocking_severities for f in actionable)),
        frozenset(f.fingerprint for f in actionable),
        phi(findings),
        render,
        error,
        hashlib.sha256(_text(section).encode()).hexdigest(),
        attempt,
        action,
    )


def accept(old: SectionState, new: SectionState, cleared: set[str], original: Section) -> bool:
    if new.render_error is not None or new.fingerprints & cleared:
        return False
    return new.phi < old.phi or (
        new.phi == old.phi
        and new.fingerprints <= old.fingerprints
        and edit_distance(original, new.section) < edit_distance(original, old.section)
    )


@dataclass
class SectionResult:
    status: Literal["clean", "residual"]
    state: SectionState
    history: list[SectionState]
    attempts: int = 0
    rejected: list[str] = field(default_factory=list)


async def _candidate(
    job: JobLike, ctx: LoopContext, state: SectionState, history: list[SectionState]
) -> tuple[Section | None, str]:
    plan = route(state.findings, state.section)
    candidate = deterministic_fix(state, job)
    if candidate is not None:
        return candidate, "restructure"
    if not plan.redraft:
        return None, "redraft"
    patch = await ctx.writer.repair(job, state, history)
    doc = ctx.doc.model_copy(update={"sections": [state.section]})
    patched = apply_patch(doc, patch.model_copy(update={"base_rev": ctx.doc.rev}), ctx.fact_guard)
    return patched.sections[0], "redraft"


def _cost(ctx: LoopContext) -> float:
    if ctx.spent is None:
        return 0.0
    total = ctx.spent()
    cost = total - ctx._logged_spent
    ctx._logged_spent = total
    return cost


def _finish(ctx: LoopContext, result: SectionResult) -> SectionResult:
    if ctx.heal_log is not None:
        ctx.heal_log.finish(result, cost_usd=_cost(ctx))
    return result


async def write_section(job: JobLike, ctx: LoopContext) -> SectionResult:
    if ctx.heal_log is not None:
        entries = ctx.heal_log._finished_entries()
        if job.section_id in entries:
            entry = entries[job.section_id]
            section = Section.model_validate(entry.section)
            state = await evaluate(section, job, ctx, tag=f"{job.section_id}-resume")
            assert entry.status is not None
            return SectionResult(entry.status, state, [state], entry.attempt)
    original = await ctx.writer.draft(job)
    state = await evaluate(original, job, ctx, tag=f"{job.section_id}-0")
    history = [state]
    rejected: list[str] = []
    cleared: set[str] = set()
    attempts = 0
    stall = 0
    while state.blocking and attempts < ctx.micro_attempts:
        attempts += 1
        try:
            candidate, action = await _candidate(job, ctx, state, history)
        except PatchRejected as exc:
            rejected.append(str(exc))
            continue
        if candidate is None:
            return _finish(ctx, SectionResult("residual", state, history, attempts - 1, rejected))
        new = await evaluate(candidate, job, ctx, tag=f"{job.section_id}-{attempts}", attempt=attempts, action=action)
        if ctx.heal_log is not None:
            ctx.heal_log.attempt(state, new, cost_usd=_cost(ctx))
        oscillation = any(old.text_hash == new.text_hash for old in history)
        history.append(new)
        stall = stall + 1 if new.phi == state.phi else 0
        if accept(state, new, cleared, original):
            cleared.update(state.fingerprints - new.fingerprints)
            state = new
        if not state.blocking:
            return _finish(ctx, SectionResult("clean", state, history, attempts, rejected))
        if stall >= 2 or oscillation:
            break
    if not state.blocking:
        return _finish(ctx, SectionResult("clean", state, history, attempts, rejected))
    if ctx.best_of_n is not None:
        result = await ctx.best_of_n(state, job, ctx, original=original)
        if result is not None and not result.blocking:
            return _finish(ctx, SectionResult("clean", result, history, attempts, rejected))
    best = min(history, key=lambda item: (item.phi, item is not state))
    return _finish(ctx, SectionResult("residual", best, history, attempts, rejected))
