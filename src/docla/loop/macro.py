"""Build, inspect and repair a complete document."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from docla.agents.summariser import summary_sources
from docla.agents.writer import SectionDraft, SectionJob, draft_to_section
from docla.checks.catalogue import all_rules, document_rules
from docla.doctypes import Doctype
from docla.loop.heal_log import HealLog
from docla.loop.look import Look, LookContext, PageCritic, look
from docla.loop.micro import BestOfN, JobLike, LoopContext, SectionState, SectionWriter, phi, write_section
from docla.loop.router import deterministic_fix, route
from docla.model import Document, Finding, Patch, PatchOp, Rule, Section
from docla.render.compose import Composition, assemble, component_for, compose, font_paths
from docla.render.typst import compile_pdf
from docla.source.files import apply_to_file, current_rev
from docla.source.ids import IdStore
from docla.source.patches import TEXT_FIELDS, FactGuard
from docla.store import Cost, Residual, Version, write_version
from docla.theme import Theme
from docla.theme.rules import load_theme_rules

Summariser = Callable[[SectionJob, list[Section]], Awaitable[SectionDraft]]


@dataclass
class MacroContext:
    doc_path: Path
    theme: Theme
    writer: SectionWriter
    workdir: Path
    rules: list[Rule] | None = None
    doctype: Doctype | None = None
    summarise: Summariser | None = None
    critic: PageCritic | None = None
    fact_guard: FactGuard | None = None
    micro_attempts: int = 3
    best_of_n: BestOfN | None = None
    macro_rounds: int = 2
    max_parallel_sections: int = 6
    final: bool = False
    assets: list[Path] | None = None
    heal_log: HealLog | None = None
    spent: Callable[[], float] | None = None


def _job(doc: Document, index: int) -> SectionJob:
    section = doc.sections[index]
    component = component_for(section, doc.format, index, len(doc.sections))
    assert component is not None and section.id is not None
    return SectionJob(
        section_id=section.id,
        format=doc.format,
        intent=section.intent,
        component=component,
        outline=section.title or "",
        section=section.section,
        audience=doc.front.get("audience", ""),
        purpose=doc.front.get("purpose", ""),
    )


def _micro_context(doc: Document, ctx: MacroContext, rules: list[Rule], writer: SectionWriter) -> LoopContext:
    return LoopContext(
        doc,
        ctx.theme,
        ctx.workdir / "micro",
        writer,
        rules=rules,
        assets=ctx.assets,
        fact_guard=ctx.fact_guard,
        micro_attempts=ctx.micro_attempts,
        best_of_n=ctx.best_of_n,
        final=ctx.final,
        heal_log=ctx.heal_log,
        spent=ctx.spent,
    )


async def _draft(doc: Document, ctx: MacroContext, rules: list[Rule]) -> None:
    summaries = summary_sources(doc, ctx.doctype) if ctx.doctype else {}
    semaphore = asyncio.Semaphore(ctx.max_parallel_sections)
    micro = _micro_context(doc, ctx, rules, ctx.writer)

    async def process(index: int) -> None:
        async with semaphore:
            result = await write_section(_job(doc, index), micro)
            doc.sections[index] = result.state.section

    await asyncio.gather(
        *(
            process(i)
            for i, section in enumerate(doc.sections)
            if section.id not in summaries and section.owner != "human" and not section.lock
        )
    )
    if ctx.summarise:
        for i, section in enumerate(doc.sections):
            if section.id in summaries and section.owner != "human" and not section.lock:
                sources = summary_sources(doc, ctx.doctype)  # type: ignore[arg-type]
                job = _job(doc, i)
                doc.sections[i] = draft_to_section(await ctx.summarise(job, sources[section.id]), job)


async def _render(
    doc: Document, ctx: MacroContext, rules: list[Rule], folder: str, clean: frozenset[str]
) -> tuple[Composition, Path, Look]:
    comp = compose(doc, assets=ctx.assets)
    main = assemble(comp, ctx.workdir / folder, theme=ctx.theme)
    pdf = main.parent / f"{ctx.doc_path.stem}.pdf"
    compile_pdf(main, main.parent, pdf, font_paths(main.parent))
    result = await look(
        pdf,
        comp,
        LookContext(
            doc=doc,
            theme=ctx.theme,
            main=main,
            project=ctx.doc_path.parent,
            workdir=main.parent,
            rules=rules + document_rules(),
            critic=ctx.critic,
            final=ctx.final,
            assets=ctx.assets,
            clean_pages=clean,
        ),
    )
    return comp, pdf, result


class _CurrentWriter:
    def __init__(self, section: Section, writer: SectionWriter):
        self.section = section
        self.writer = writer

    async def draft(self, job: JobLike) -> Section:
        return self.section

    async def repair(
        self, job: JobLike, state: SectionState, history: list[SectionState], *, strategy: str | None = None
    ) -> Patch:
        return await self.writer.repair(job, state, history, strategy=strategy)


async def _repair(doc: Document, ctx: MacroContext, rules: list[Rule], findings: list[Finding]) -> bool:
    changed = False
    for i, section in enumerate(doc.sections):
        relevant = [f for f in findings if f.section_id == section.id]
        plan = route(relevant, section)
        if not plan.actionable():
            continue
        job = _job(doc, i)
        candidate = deterministic_fix(SimpleNamespace(section=section, findings=relevant), job)
        if candidate is None and plan.redraft:
            micro = _micro_context(doc, ctx, rules, _CurrentWriter(section, ctx.writer))
            result = await write_section(job, micro)
            candidate = result.state.section
        if candidate is not None and candidate != section:
            doc.sections[i] = candidate
            changed = True
    return changed


def _write_back(original: Document, doc: Document, ctx: MacroContext) -> Document:
    ops = []
    for before, after in zip(original.sections, doc.sections, strict=True):
        if before == after:
            continue
        assert after.id is not None
        fields = after.model_dump(include=set(TEXT_FIELDS), mode="json")
        if before.component != after.component or before.because != after.because:
            fields.update(component=after.component, because=after.because)
        ops.append(PatchOp(op="set_fields", section_id=after.id, fields=fields))
    if not ops:
        return doc
    project = ctx.doc_path.parent / ".docla"
    oplog = project / "oplog.jsonl"
    patch = Patch(base_rev=current_rev(oplog), author="ai", reason="Macro loop", ops=ops)
    return apply_to_file(ctx.doc_path, patch, oplog, IdStore(project / "ids.json"))


def _residual(findings: list[Finding], stopped: bool) -> list[Residual]:
    seen = set()
    result = []
    for finding in findings:
        if finding.severity == "info" or finding.fingerprint in seen:
            continue
        seen.add(finding.fingerprint)
        remedy = finding.remedy.class_
        reason = remedy if remedy in ("engine", "report", "ask") else "no progress" if stopped else "rounds"
        result.append(Residual(finding=finding.id, reason=reason))
    return result


async def build_document(doc: Document, ctx: MacroContext) -> Version:
    original = doc.model_copy(deep=True)
    doc = doc.model_copy(deep=True)
    rules = ctx.rules if ctx.rules is not None else all_rules() + load_theme_rules(ctx.theme)
    await _draft(doc, ctx, rules)
    previous = None
    clean: frozenset[str] = frozenset()
    changed = False
    stopped = False
    for r in range(1, ctx.macro_rounds + 1):
        comp, pdf, result = await _render(doc, ctx, rules, f"round-{r}", clean)
        clean = result.clean_pages
        actionable = [
            f for s in doc.sections for f in route([f for f in result.findings if f.section_id == s.id], s).actionable()
        ]
        signature = (phi(result.findings), frozenset(f.fingerprint for f in actionable))
        if not actionable or (previous is not None and (signature[0] > previous[0] or signature == previous)):
            stopped = True
            changed = False
            break
        previous = signature
        changed = await _repair(doc, ctx, rules, result.findings)
        if not changed:
            stopped = True
            break
    if changed or ctx.macro_rounds == 0:
        comp, pdf, result = await _render(doc, ctx, rules, "final", clean)
    doc = _write_back(original, doc, ctx)
    heal = ctx.heal_log.path if ctx.heal_log else None
    return write_version(
        ctx.doc_path,
        doc,
        comp,
        pdf,
        result.facts,
        result.findings,
        result.pngs,
        heal,
        theme=ctx.theme,
        final=ctx.final,
        look=result.record(),
        residual=_residual(result.findings, stopped),
        cost=Cost(usd=ctx.spent() if ctx.spent else 0.0),
    )
