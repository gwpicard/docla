"""Run the seeded section repair evaluation."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from docla.agents.writer import SectionJob
from docla.loop.guards import FactGuard
from docla.loop.micro import LoopContext, SectionWriter, write_section
from docla.model import Document, Patch, PatchOp, Section
from docla.render.compose import component_for
from docla.source.parser import parse
from docla.theme import Theme


class HealCase(BaseModel):
    id: str
    file: str
    kind: str
    rule: str
    facts: list[str]
    repair: dict[str, Any]
    document: Document


def load_cases(folder: Path) -> list[HealCase]:
    data = yaml.safe_load((folder / "cases.yaml").read_text())
    cases = []
    for entry in data["cases"]:
        document, findings = parse((folder / entry["file"]).read_text())
        if any(f.severity == "error" for f in findings):
            raise ValueError(f"Invalid case: {entry['id']}")
        cases.append(HealCase(**entry, document=document))
    return cases


def section_text(section: Section) -> str:
    return "\n".join(
        [
            section.title or "",
            *section.paragraphs,
            *section.code,
            *(value or "" for value in (section.note, section.spoken, section.source_line)),
            *(value for item in section.items for value in (item.head or "", item.body, *item.sub)),
        ]
    )


class ScriptedWriter:
    def __init__(self, case: HealCase):
        self.case = case

    async def draft(self, job: Any) -> Section:
        return self.case.document.sections[0]

    async def repair(self, job: Any, state: Any, history: Any, *, strategy: str | None = None) -> Patch:
        return Patch(
            base_rev=self.case.document.rev,
            author="ai",
            reason="repair",
            ops=[PatchOp(op="set_fields", section_id=job.section_id, fields=self.case.repair)],
        )


@dataclass
class CaseResult:
    case: HealCase
    status: str
    attempts: int
    facts_kept: int


@dataclass
class HealReport:
    results: list[CaseResult]
    cost: float
    mode: str = "offline"

    @property
    def gate(self) -> bool:
        n = len(self.results)
        total = sum(len(r.case.facts) for r in self.results)
        return bool(
            n
            and total
            and sum(r.status == "clean" for r in self.results) / n >= 0.9
            and sum(r.facts_kept for r in self.results) / total >= 0.99
        )


async def run_heal(
    cases: list[HealCase],
    *,
    writer_for: Callable[[HealCase], SectionWriter],
    theme: Theme,
    workdir: Path,
    spent: Callable[[], float] = lambda: 0.0,
) -> HealReport:
    results = []
    for case in cases:
        doc = case.document
        section = doc.sections[0]
        component = component_for(section, "slides")
        assert component is not None
        job = SectionJob(
            section_id=section.id,
            format="slides",
            intent=section.intent,
            component=component,
            outline=section.title or "",
            section=section.section,
        )
        evidence = [section_text(section), *(f"{s.key} {s.text}" for s in doc.sources)]
        ctx = LoopContext(
            doc,
            theme,
            workdir / case.id,
            writer_for(case),
            fact_guard=FactGuard(evidence, {s.key for s in doc.sources}),
            micro_attempts=3,
            best_of_n=None,
            blocking_severities=frozenset({"error", "warning"}),
            final=True,
        )
        result = await write_section(job, ctx)
        kept = sum(fact in section_text(result.state.section) for fact in case.facts)
        results.append(CaseResult(case, result.status, result.attempts, kept))
    return HealReport(results, spent())


def render_results(report: HealReport) -> str:
    results = report.results
    n = len(results)
    cleared = sum(r.status == "clean" and r.attempts <= 3 for r in results)
    kept = sum(r.facts_kept for r in results)
    total = sum(len(r.case.facts) for r in results)

    def percent(a, b):
        return 100 * a / b if b else 0.0

    lines = [
        "# Heal eval",
        "",
        f"Mode: {report.mode}",
        f"Cases: {n}",
        f"Cleared in at most 3 attempts: {cleared} / {n} ({percent(cleared, n):.1f}%)",
        f"Mean attempts: {sum(r.attempts for r in results) / n if n else 0:.2f}",
        f"Cost: ${report.cost:.4f}",
        f"Facts kept: {kept} / {total} ({percent(kept, total):.1f}%)",
        f"Gate: {'met' if report.gate else 'not met'}",
        "",
        "| Case | Kind | Rule | Status | Attempts | Facts kept |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {r.case.id} | {r.case.kind} | {r.case.rule} | {r.status} | {r.attempts} | "
        f"{r.facts_kept} / {len(r.case.facts)} |"
        for r in results
    )
    return "\n".join(lines) + "\n"
