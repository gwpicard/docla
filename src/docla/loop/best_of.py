"""Generate and score alternative repairs for a stalled section."""

import asyncio
from itertools import cycle, islice
from typing import cast

from docla.loop.guards import fact_tokens, kept_facts
from docla.loop.micro import JobLike, LoopContext, SectionState, edit_distance, evaluate
from docla.loop.router import ACTIONABLE
from docla.model import Section
from docla.source.patches import PatchRejected, apply_patch

STRATEGIES: list[str] = [
    "Cut the lowest-priority item.",
    "Compress every item to its head.",
    "Merge two items.",
]


def fact_preservation(original: Section, candidate: Section) -> float:
    facts = fact_tokens(original)
    return len(kept_facts(original, candidate)) / len(facts) if facts else 1.0


def score(candidate: SectionState, original: Section) -> tuple[int, int, float, int]:
    if candidate.render_error is not None:
        return (cast(int, float("inf")), 0, 0.0, 0)
    actionable = [finding for finding in candidate.findings if finding.remedy.class_ in ACTIONABLE]
    return (
        sum(f.severity == "error" for f in actionable),
        sum(f.severity == "warning" for f in actionable),
        -fact_preservation(original, candidate.section),
        edit_distance(original, candidate.section),
    )


async def best_of_n(
    state: SectionState, job: JobLike, ctx: LoopContext, n: int = 3, *, original: Section | None = None
) -> SectionState | None:
    original = state.section if original is None else original
    candidates = []
    for k, strategy in enumerate(islice(cycle(STRATEGIES), max(0, n))):
        patch = await ctx.writer.repair(job, state, [state], strategy=strategy)
        doc = ctx.doc.model_copy(update={"sections": [state.section]})
        try:
            patched = apply_patch(doc, patch.model_copy(update={"base_rev": ctx.doc.rev}), ctx.fact_guard)
        except PatchRejected:
            continue
        candidates.append(evaluate(patched.sections[0], job, ctx, tag=f"{job.section_id}-best-{k}", action="best-of-n"))
    evaluated = await asyncio.gather(*candidates)
    return min(evaluated, key=lambda candidate: score(candidate, original), default=None)
