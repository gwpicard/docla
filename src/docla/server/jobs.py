"""Background jobs for the visualiser."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, TypeAdapter, field_validator

import docla.write as write
from docla.agents.gatherer import Fact
from docla.agents.ledger import Ledger
from docla.agents.scheduler import Scheduler
from docla.checks.catalogue import all_rules
from docla.config import load_project_config
from docla.doctypes import load_doctypes
from docla.loop.guards import FactGuard
from docla.loop.heal_log import HealLog
from docla.loop.macro import MacroContext, _job, build_document
from docla.loop.micro import LoopContext, evaluate, write_section
from docla.model import Finding, Remedy
from docla.server.events import EventBus
from docla.server.themes import document_theme
from docla.source.patches import apply_patch
from docla.theme import Theme
from docla.theme.rules import load_theme_rules
from docla.write import _DraftedWriter

Kind = Literal["build", "redraft"]
Progress = Callable[[dict[str, Any]], None]
Work = Callable[[Progress], Awaitable[dict[str, Any]]]


class Job(BaseModel):
    id: str
    kind: Kind
    doc: str
    status: Literal["running", "finished", "failed"] = "running"
    result: dict[str, Any] | None = None
    error: str | None = None


class JobRunner:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.jobs: dict[str, Job] = {}
        self.tasks: set[asyncio.Task[None]] = set()

    def start(self, kind: Kind, doc: str, work: Work) -> Job:
        job = Job(id=uuid4().hex, kind=kind, doc=doc)
        self.jobs[job.id] = job
        loop = asyncio.get_running_loop()
        base = {"id": job.id, "kind": kind, "doc": doc}
        self.bus.publish("job.started", base)

        def progress(data: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(self.bus.publish, "job.progress", {**base, **data})

        async def run() -> None:
            try:

                async def execute() -> dict[str, Any]:
                    return await work(progress)

                job.result = await asyncio.to_thread(asyncio.run, execute())
                job.status = "finished"
            except Exception as error:
                job.error = str(error)
                job.status = "failed"
            self.bus.publish("job.finished", {**base, "status": job.status, "result": job.result, "error": job.error})

        task = asyncio.create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)


def _agents(app: Any, theme: Theme) -> write.Agents:
    if app.state.agents is not None:
        return cast(write.Agents, app.state.agents)
    if theme.root not in app.state.agents_by_theme:
        project = app.state.project
        config = load_project_config(project)
        claude = write.ScheduledClaude(
            write.transport_for(project),
            Ledger(project / ".docla" / "server" / "ledger.jsonl", config.prices, config.budget.max_usd_per_document),
            write.role_models(config),
            scheduler=Scheduler(config.loop.max_parallel_sections),
        )
        app.state.agents_by_theme[theme.root] = write.claude_agents(claude, theme, config=config)
    return cast(write.Agents, app.state.agents_by_theme[theme.root])


def _facts(project: Path, doc: str) -> list[Fact]:
    path = project / ".docla" / "write" / doc / "facts.json"
    return TypeAdapter(list[Fact]).validate_json(path.read_text()) if path.exists() else []


def _stale(oplog: Path, rev: int) -> bool:
    if not oplog.exists():
        return False
    return any(json.loads(line).get("author") != "ai" for line in oplog.read_text().splitlines()[rev:])


class BuildBody(BaseModel):
    mode: Literal["draft", "final"]


class RedraftBody(BaseModel):
    ask: str

    @field_validator("ask")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ask must not be blank")
        return value


router = APIRouter()


@router.post("/api/docs/{doc}/build", status_code=202)
async def build(doc: str, body: BuildBody, request: Request) -> dict[str, str]:
    app = request.app
    snapshot = app.state.docs.load(doc)
    path = app.state.docs.path(doc)
    loop = asyncio.get_running_loop()
    job_id = ""

    async def work(progress: Progress) -> dict[str, Any]:
        theme = document_theme(app.state, snapshot)
        agents = _agents(app, theme)
        writer = _DraftedWriter(snapshot, agents.writer(_facts(app.state.project, doc), snapshot))
        workdir = app.state.project / ".docla" / "render" / "jobs" / job_id
        name = snapshot.front.get("doctype")
        doctype = load_doctypes().get(name) if isinstance(name, str) else None
        progress({"stage": "building", "rev": snapshot.rev})
        version = await build_document(
            snapshot,
            MacroContext(
                doc_path=path,
                theme=theme,
                writer=writer,
                workdir=workdir,
                doctype=doctype,
                summarise=agents.summariser(snapshot) if agents.summariser else None,
                critic=agents.critic(snapshot) if agents.critic else None,
                final=body.mode == "final",
                heal_log=HealLog(workdir),
            ),
        )
        stale = _stale(app.state.docs.oplog, snapshot.rev)
        loop.call_soon_threadsafe(
            app.state.bus.publish, "build.finished", {"doc": doc, "version": version.number, "stale": stale}
        )
        return {"version": version.number, "stale": stale, "snapshot_rev": snapshot.rev}

    job = app.state.jobs.start("build", doc, work)
    job_id = job.id
    return {"job": job.id}


def _evidence(doc: Any, facts: list[Fact]) -> list[str]:
    evidence = [fact.text for fact in facts] + [f"{s.key} {s.text}" for s in doc.sources]
    evidence += [value for value in doc.front.values() if isinstance(value, str)]
    for section in doc.sections:
        evidence.extend([section.title or "", section.source_line or "", *section.paragraphs])
        evidence.extend(value for item in section.items for value in (item.head or "", item.body, *item.sub))
    return evidence


@router.post("/api/docs/{doc}/sections/{section_id}/redraft", status_code=202)
async def redraft(doc: str, section_id: str, body: RedraftBody, request: Request) -> dict[str, str]:
    app = request.app
    snapshot = app.state.docs.load(doc)
    index = next((i for i, s in enumerate(snapshot.sections) if s.id == section_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Unknown section")
    original = snapshot.sections[index].model_copy(deep=True)
    section = original.model_copy(update={"owner": None, "lock": None}, deep=True)
    job_id = ""

    async def work(progress: Progress) -> dict[str, Any]:
        theme = document_theme(app.state, snapshot)
        facts = _facts(app.state.project, doc)
        writer = _agents(app, theme).writer(facts, snapshot)
        guard = FactGuard(_evidence(snapshot, facts), {s.key for s in snapshot.sources})
        workdir = app.state.project / ".docla" / "render" / "jobs" / job_id
        ctx = LoopContext(
            snapshot,
            theme,
            workdir,
            writer,
            rules=all_rules() + load_theme_rules(theme),
            fact_guard=guard,
        )
        section_job = _job(snapshot, index)
        state = await evaluate(section, section_job, ctx, tag="ask-0")
        state.findings.append(
            Finding(
                id=f"human.ask:{section_id}",
                rule_id="human.ask",
                tier="source",
                severity="error",
                format=snapshot.format,
                section_id=section_id,
                message=body.ask,
                remedy=Remedy.model_validate({"class": "redraft", "hint": body.ask}),
                fingerprint=f"human.ask:{section_id}",
            )
        )
        patch = await writer.repair(section_job, state, [state])
        one = snapshot.model_copy(update={"sections": [section]}, deep=True)
        candidate = apply_patch(one, patch, guard).sections[0]
        ctx.writer = _DraftedWriter(one.model_copy(update={"sections": [candidate]}), writer)
        result = await write_section(section_job, ctx)
        return {
            "section_id": section_id,
            "before": original.model_dump(mode="json"),
            "after": result.state.section.model_dump(mode="json"),
            "status": result.status,
            "findings": [f.model_dump(mode="json", by_alias=True) for f in result.state.findings],
        }

    job = app.state.jobs.start("redraft", doc, work)
    job_id = job.id
    return {"job": job.id}
