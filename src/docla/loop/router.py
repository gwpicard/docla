"""Route findings and select deterministic section remedies."""

from dataclasses import dataclass, field
from typing import Protocol

from docla.model import Finding, Format, Section
from docla.render.chooser import Chooser
from docla.render.compose import default_chooser

ACTIONABLE: tuple[str, ...] = ("redraft", "restructure", "tune")


@dataclass
class Plan:
    redraft: list[Finding] = field(default_factory=list)
    restructure: list[Finding] = field(default_factory=list)
    tune: list[Finding] = field(default_factory=list)
    engine: list[Finding] = field(default_factory=list)
    report: list[Finding] = field(default_factory=list)
    ask: list[Finding] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)

    def actionable(self) -> list[Finding]:
        return self.redraft + self.restructure + self.tune


def route(findings: list[Finding], section: Section) -> Plan:
    """Partition findings by remedy, reporting actions blocked by locks."""
    plan = Plan()
    for finding in findings:
        remedy = finding.remedy.class_
        note = _lock_note(remedy, section)
        if note is not None:
            plan.report.append(finding)
            plan.notes[finding.id] = note
        else:
            getattr(plan, remedy).append(finding)
    return plan


def _lock_note(remedy: str, section: Section) -> str | None:
    if remedy == "redraft" and (section.lock in ("text", "all") or section.owner == "human"):
        return "section is locked; not redrafted"
    if section.lock == "all" and remedy in ("restructure", "tune"):
        return f"section is locked; not {'restructured' if remedy == 'restructure' else 'tuned'}"
    return None


class RouteState(Protocol):
    section: Section
    findings: list[Finding]


class RouteJob(Protocol):
    format: Format


def deterministic_fix(state: RouteState, job: RouteJob, chooser: Chooser | None = None) -> Section | None:
    """Advance to the next matching component for a restructure finding."""
    findings = route(state.findings, state.section).restructure
    if not findings or state.section.lock == "all":
        return None
    chooser = default_chooser() if chooser is None else chooser
    section = state.section
    chosen = chooser.choose(section, job.format, 0, 1)
    order = [chosen, *chooser.alternates(section, job.format, 0, 1)]
    current = section.component if section.component in chooser.names(job.format) else chosen
    if current not in order or order.index(current) == len(order) - 1:
        return None
    next_component = order[order.index(current) + 1]
    rules = ", ".join(finding.rule_id for finding in findings)
    return section.model_copy(
        update={"component": next_component, "because": f"router: switched from {current} after {rules}"}
    )
