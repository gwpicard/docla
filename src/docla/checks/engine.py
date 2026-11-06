import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, get_args

from docla.facts.layout import LayoutFacts
from docla.model import Box, Document, Finding, Rule
from docla.model.rules import Severity, Tier
from docla.render.compose import Composition
from docla.theme import Theme

# Tiers run in the order the model declares them.
TIERS: tuple[Tier, ...] = get_args(Tier)
GRID = 8


@dataclass
class CheckContext:
    doc: Document
    facts: LayoutFacts | None = None
    tokens: dict[str, str] = field(default_factory=dict)
    theme: Theme | None = None
    composition: Composition | None = None
    final: bool = False


class Check(Protocol):
    tier: Tier | None

    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]: ...


CHECKS: dict[str, Check] = {}


class UnknownCheckError(KeyError):
    pass


def register(kind: str) -> Callable[[type], type]:
    def decorate(cls: type) -> type:
        if kind in CHECKS:
            raise ValueError(f"check kind {kind!r} is already registered")
        CHECKS[kind] = cls()
        return cls

    return decorate


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()


def _cell(region: Box | None, page_size: tuple[float, float] | None) -> str:
    if region is None or page_size is None:
        return "-"
    width, height = page_size
    col = int((region.x + region.w / 2) / width * GRID)
    row = int((region.y + region.h / 2) / height * GRID)
    return f"{min(max(col, 0), GRID - 1)},{min(max(row, 0), GRID - 1)}"


def fingerprint(
    rule_id: str,
    section_id: str | None,
    role: str | None,
    region: Box | None,
    page_size: tuple[float, float] | None,
) -> str:
    return _sha1(f"{rule_id}|{section_id}|{role}|{_cell(region, page_size)}")


def _page_size(ctx: CheckContext, page: int | None) -> tuple[float, float] | None:
    if ctx.facts is None or not ctx.facts.pages:
        return None
    pages = ctx.facts.pages
    chosen = next((p for p in pages if p.page == page), pages[0])
    return (chosen.width, chosen.height)


def make_finding(
    rule: Rule,
    ctx: CheckContext,
    *,
    message: str,
    section_id: str | None = None,
    role: str | None = None,
    page: int | None = None,
    region: Box | None = None,
    measured: dict[str, Any] | None = None,
    severity: Severity | None = None,
) -> Finding:
    fp = fingerprint(rule.id, section_id, role, region, _page_size(ctx, page))
    return Finding(
        id=_sha1(f"{rule.id}|{section_id}|{fp}")[:12],
        rule_id=rule.id,
        tier=rule.tier,
        severity=severity if severity is not None else rule.severity,
        format=ctx.doc.format,
        section_id=section_id,
        page=page,
        region=region,
        message=message,
        measured=measured or {},
        fingerprint=fp,
        remedy=rule.remedy,
    )


def _applies(rule: Rule, ctx: CheckContext) -> bool:
    if rule.status not in ("active", "probation"):
        return False
    return rule.scope.format is None or rule.scope.format == ctx.doc.format


def _check_for(rule: Rule) -> Check:
    kind = rule.check["kind"]
    if kind not in CHECKS:
        raise UnknownCheckError(f"no check registered for kind {kind!r}")
    return CHECKS[kind]


def _tiers_to_run(ctx: CheckContext) -> tuple[Tier, ...]:
    return TIERS if ctx.facts is not None else ("source",)


def _in_scope(finding: Finding, rule: Rule, ctx: CheckContext) -> bool:
    scope = rule.scope
    if scope.components is not None and (
        ctx.composition is None
        or not any(s.id == finding.section_id and s.component in scope.components for s in ctx.composition.sections)
    ):
        return False
    if scope.intents is not None and not any(
        s.id is not None and s.id == finding.section_id and s.intent in scope.intents for s in ctx.doc.sections
    ):
        return False
    return True


def run_checks(rules: list[Rule], ctx: CheckContext) -> list[Finding]:
    applicable = [(rule, _check_for(rule)) for rule in rules if _applies(rule, ctx)]
    blocked: set[str | None] = set()
    findings: list[Finding] = []
    for tier in _tiers_to_run(ctx):
        produced = [
            f
            for rule, check in applicable
            if (check.tier or rule.tier) == tier
            for f in check.run(ctx, rule)
            if _in_scope(f, rule, ctx)
        ]
        kept = [f for f in produced if f.section_id not in blocked]
        blocked |= {f.section_id for f in kept if f.severity == "error"}
        findings.extend(kept)
    return _unique(findings)


def _unique(findings: list[Finding]) -> list[Finding]:
    seen: set[str] = set()
    unique: list[Finding] = []
    for finding in findings:
        if finding.fingerprint not in seen:
            seen.add(finding.fingerprint)
            unique.append(finding)
    return unique
