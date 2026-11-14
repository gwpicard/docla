"""Prepare and draft a reviewable working file."""

import asyncio
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from docla.agents.cassette import Cassette, Transport
from docla.agents.client import AnthropicTransport, CassetteTransport, Claude
from docla.agents.critic import CriticImage, calibrate, corroborate
from docla.agents.gatherer import Fact, gather, with_fact_ids
from docla.agents.ledger import BudgetExceeded
from docla.agents.planner import outline_to_document, plan
from docla.agents.prompts import ROLES
from docla.agents.scheduler import Scheduler
from docla.agents.summariser import summarise, summary_sources
from docla.agents.writer import SectionJob, draft, draft_to_section, repair
from docla.checks.catalogue import all_rules
from docla.config import ProjectConfig, load_project_config
from docla.doctypes import load_doctypes
from docla.loop.best_of import best_of_n
from docla.loop.guards import FactGuard
from docla.loop.heal_log import HealLog
from docla.loop.look import CriticPage, PageCritic
from docla.loop.macro import MacroContext, Summariser, build_document
from docla.loop.micro import LoopContext, write_section
from docla.loop.router import ACTIONABLE
from docla.model import Document, Finding, Patch, PatchOp, Source
from docla.render.components import all_manifests
from docla.render.compose import component_for
from docla.source.files import apply_to_file, current_rev
from docla.source.ids import IdStore, stamp
from docla.source.parser import parse
from docla.source.patches import TEXT_FIELDS
from docla.source.serialiser import serialise
from docla.sources import extract
from docla.theme.brief import brief_card
from docla.theme.rubric import load_calibration, load_rubric

ESTIMATE_USD_PER_SECTION = 0.10


@dataclass
class Agents:
    gather: Callable[..., Any]
    outline: Callable[..., Any]
    writer: Callable[..., Any]
    critic: Callable[[Document], PageCritic] | None = None
    summariser: Callable[[Document], Summariser] | None = None


class ScheduledClaude(Claude):
    def __init__(self, transport: Any, ledger: Any, models: dict[str, str], *, scheduler: Scheduler) -> None:
        super().__init__(transport, ledger, models)
        self.scheduler = scheduler

    async def call(self, *args: Any, **kwargs: Any) -> Any:
        return await self.scheduler.run(lambda: super(ScheduledClaude, self).call(*args, **kwargs))

    async def cite(self, *args: Any, **kwargs: Any) -> Any:
        return await self.scheduler.run(lambda: super(ScheduledClaude, self).cite(*args, **kwargs))


def role_models(config: ProjectConfig) -> dict[str, str]:
    models = config.models
    return {
        **models,
        **{role: models.get(role, models["critic" if role == "planner" else "writer"]) for role in ROLES},
        "summariser": models.get("summariser", models["writer"]),
    }


def live_transport() -> Transport:
    return AnthropicTransport()


def transport_for(project: Path) -> Transport:
    path = project / ".docla" / "cassette.json"
    if os.environ.get("DOCLA_LIVE") != "1":
        return CassetteTransport(Cassette(path, "replay"))
    transport = live_transport()
    if os.environ.get("DOCLA_RECORD") == "1":
        return CassetteTransport(Cassette(path, "record", transport=transport))
    return transport


class ClaudeWriter:
    def __init__(self, claude: Any, facts: Any, theme: Any, doc: Any) -> None:
        self.claude, self.facts, self.theme, self.doc = claude, facts, theme, doc
        self.drafts: dict[str, Any] = {}

    def card(self, job: Any) -> str:
        return brief_card(self.theme, job.format, job.intent, all_manifests()[job.component], all_rules())

    async def draft(self, job: Any) -> Any:
        result = await draft(self.claude, job, self.facts, self.card(job), None, theme=self.theme)
        self.drafts[job.section_id] = result
        return draft_to_section(result, job)

    async def repair(self, job: Any, state: Any, history: Any, *, strategy: Any = None) -> Any:
        lines = [
            f"attempt {s.attempt}: {s.action}; findings {', '.join(f.rule_id for f in s.findings)}" for s in history
        ]
        previous = self.drafts.get(job.section_id)
        if previous is not None and len(previous.items) == len(state.section.items):
            lines.append(
                "draft priority: " + ", ".join(f"items[{i}]={item.priority}" for i, item in enumerate(previous.items))
            )
        if strategy is not None:
            lines.append(f"strategy: {strategy}")
        findings = [f for f in state.findings if f.remedy.class_ in ACTIONABLE]
        return await repair(self.claude, state.section, findings, lines, self.card(job), theme=self.theme)


class ClaudeCritic:
    def __init__(self, claude: Any, theme: Any, format: Any, *, act_on_uncorroborated: bool = False) -> None:
        self.claude, self.format = claude, format
        self.rubric = load_rubric(theme)
        self.calibration = load_calibration(theme)
        self.act_on_uncorroborated = act_on_uncorroborated

    async def __call__(self, page: CriticPage) -> list[Finding]:
        ids = {
            item.id
            for sid in page.sections
            for item in self.rubric.applies(self.format, page.components.get(sid), page.intents.get(sid), view="page")
        }
        items = [item for item in self.rubric.items if item.id in ids]
        if not items:
            return []
        findings = await corroborate(
            self.claude,
            [CriticImage(page.png, page.page, page.width, page.height, f"page {page.page}")],
            items,
            page.findings,
            page.regions,
            format=self.format,
        )
        return calibrate(findings, self.calibration, act_on_uncorroborated=self.act_on_uncorroborated)


class ClaudeSummariser:
    def __init__(self, claude: Any, theme: Any, brief: str) -> None:
        self.claude, self.theme, self.brief = claude, theme, brief

    async def __call__(self, job: Any, sections: Any) -> Any:
        return await summarise(self.claude, sections, job=job, brief=self.brief, theme=self.theme)


def claude_agents(claude: Any, theme: Any, *, config: ProjectConfig | None = None) -> Agents:
    config = config or ProjectConfig()

    async def gather_sources(extracted: Any) -> Any:
        return await gather(claude, extracted)

    async def outline(facts: Any, doctype: Any, front: Any, store: Any) -> Any:
        brief = "\n".join(f"{key}: {front.get(key, '')}" for key in ("audience", "purpose"))
        result = await plan(claude, facts, doctype, brief, theme=theme)
        return outline_to_document(result, front, store=store), result.questions

    def summariser_factory(doc: Document) -> ClaudeSummariser:
        brief = "\n".join(f"{key}: {doc.front.get(key, '')}" for key in ("audience", "purpose"))
        return ClaudeSummariser(claude, theme, brief)

    return Agents(
        gather_sources,
        outline,
        lambda facts, doc: ClaudeWriter(claude, facts, theme, doc),
        critic=lambda doc: ClaudeCritic(
            claude, theme, doc.format, act_on_uncorroborated=config.loop.act_on_uncorroborated
        ),
        summariser=summariser_factory,
    )


async def _facts(project: Any, run_dir: Any, agents: Any) -> Any:
    from docla.tables import typed_table_facts

    path = run_dir / "facts.json"
    if path.exists():
        return with_fact_ids(typed_table_facts(TypeAdapter(list[Fact]).validate_json(path.read_text()), project))
    facts = with_fact_ids(typed_table_facts(await agents.gather(extract(project)), project))
    run_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(TypeAdapter(list[Fact]).dump_json(facts, indent=2))
    return facts


def _outline_output(file: Any, doc: Any, questions: Any = ()) -> None:
    for section in doc.sections:
        print(f"{section.id} {section.intent} {section.title}")
    for question in questions:
        print(f"question: {question}")
    print(f"approve the outline with: docla write {file} --approve")


async def _make_outline(file: Any, doc: Any, agents: Any, run_dir: Any, ids: Any) -> None:
    from docla.tables import typed_table_facts

    extracted = extract(file.parent)
    facts = with_fact_ids(typed_table_facts(await agents.gather(extracted), file.parent))
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "facts.json").write_bytes(TypeAdapter(list[Fact]).dump_json(facts, indent=2))
    front = {**doc.front, "format": doc.format}
    doc, questions = await agents.outline(facts, load_doctypes()[front["doctype"]], front, ids)
    doc, _ = stamp(doc, ids)
    ids.save()
    doc.sources = [Source(key=s.key, text=s.name) for s in extracted]
    file.write_text(serialise(doc))
    _outline_output(file, doc, questions)


class _DraftedWriter:
    def __init__(self, doc: Document, writer: Any) -> None:
        self.doc, self.writer = doc, writer

    async def draft(self, job: Any) -> Any:
        return next(section for section in self.doc.sections if section.id == job.section_id).model_copy(deep=True)

    async def repair(self, job: Any, state: Any, history: Any, *, strategy: Any = None) -> Any:
        return await self.writer.repair(job, state, history, strategy=strategy)


async def run_write(
    file: Path,
    *,
    agents: Agents,
    theme: Any,
    out: Path,
    approve: bool,
    yes: bool = False,
    confirm: Callable[[str], str] = input,
    spent: Callable[[], float] = lambda: 0.0,
) -> int:
    project = file.parent
    run_dir = project / ".docla" / "write" / file.stem
    oplog = project / ".docla" / "oplog.jsonl"
    ids = IdStore(project / ".docla" / "ids.json")
    doc, _ = parse(file.read_text())
    if not approve:
        if doc.sections:
            _outline_output(file, doc)
        else:
            await _make_outline(file, doc, agents, run_dir, ids)
        return 0
    if not doc.sections:
        print("no outline", file=sys.stderr)
        return 2
    if len(doc.sections) > 40:
        print(f"estimate: {len(doc.sections)} sections, about ${len(doc.sections) * ESTIMATE_USD_PER_SECTION:.2f}")
        if not yes and confirm("continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("cancelled")
            return 1
    try:
        facts = await _facts(project, run_dir, agents)
        config = load_project_config(project)
        assets = [project / "assets", theme.root / "assets"]
        evidence = [f.text for f in facts] + [f"{s.key} {s.text}" for s in doc.sources]
        evidence += [v for v in doc.front.values() if isinstance(v, str)]
        ctx = LoopContext(
            doc,
            theme,
            run_dir,
            agents.writer(facts, doc),
            assets=assets,
            fact_guard=FactGuard(evidence, {s.key for s in doc.sources}, facts=facts),
            micro_attempts=config.loop.micro_attempts,
            best_of_n=partial(best_of_n, n=config.loop.best_of_n),
            heal_log=HealLog(run_dir),
            spent=spent,
        )
        doctype_name = doc.front.get("doctype")
        doctype = load_doctypes().get(doctype_name) if isinstance(doctype_name, str) else None
        summaries = summary_sources(doc, doctype) if doctype else {}
        semaphore = asyncio.Semaphore(config.loop.max_parallel_sections)

        async def process(i: int, section: Any) -> str:
            async with semaphore:
                component = component_for(section, doc.format, i, len(doc.sections))
                assert component is not None
                job = SectionJob(
                    section_id=section.id,
                    format=doc.format,
                    intent=section.intent,
                    component=component,
                    outline=section.title or "",
                    section=section.section,
                    audience=doc.front.get("audience", ""),
                    purpose=doc.front.get("purpose", ""),
                )
                result = await write_section(job, ctx)
                fields = result.state.section.model_dump(include=set(TEXT_FIELDS), mode="json")
                if result.state.section.component != section.component:
                    fields.update(component=result.state.section.component, because=result.state.section.because)
                patch = Patch(
                    base_rev=current_rev(oplog),
                    author="ai",
                    reason="Draft section",
                    ops=[PatchOp(op="set_fields", section_id=section.id, fields=fields)],
                )
                apply_to_file(file, patch, oplog, ids)
                print(f"section {section.id}: {result.status}; total cost ${spent():.4f}")
                return result.status

        statuses = await asyncio.gather(
            *(
                process(i, s)
                for i, s in enumerate(doc.sections)
                if s.owner != "human" and not s.lock and s.id not in summaries
            )
        )
        updated, _ = parse(file.read_text())
        macro_dir = out / "macro"
        if macro_dir.exists():
            shutil.rmtree(macro_dir)
        version = await build_document(
            updated,
            MacroContext(
                doc_path=file,
                theme=theme,
                writer=_DraftedWriter(updated, ctx.writer),
                workdir=macro_dir,
                doctype=doctype,
                summarise=agents.summariser(updated) if agents.summariser else None,
                critic=agents.critic(updated) if agents.critic else None,
                fact_guard=ctx.fact_guard,
                micro_attempts=config.loop.micro_attempts,
                best_of_n=ctx.best_of_n,
                macro_rounds=config.loop.macro_rounds,
                max_parallel_sections=config.loop.max_parallel_sections,
                assets=assets,
                heal_log=ctx.heal_log,
                spent=spent,
            ),
        )
        pdf = out / f"{file.stem}.pdf"
        shutil.copyfile(version.path / pdf.name, pdf)
        print(pdf)
        print(version.path)
        return int(any(status != "clean" for status in statuses))
    except BudgetExceeded as error:
        print(error, file=sys.stderr)
        return 1
