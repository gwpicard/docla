from dataclasses import dataclass
from typing import Any, Literal

from docla.checks.engine import CHECKS, CheckContext, UnknownCheckError, make_finding, register
from docla.facts.layout import PlacedShape, PlacedWord
from docla.model import Finding, Rule, Section


@dataclass(frozen=True)
class Selected:
    kind: Literal["text", "shape", "section"]
    section_id: str | None
    role: str | None
    fact: PlacedWord | PlacedShape | Section


def _matches(value: str | None, criterion: Any) -> bool:
    if criterion is None or criterion == "any":
        return True
    if value is None:
        return False
    return value in criterion if isinstance(criterion, list) else value == criterion


def _selected(ctx: CheckContext, kind: str) -> list[Selected]:
    if kind == "section":
        return [Selected("section", section.id, None, section) for section in ctx.doc.sections]
    if ctx.facts is None:
        return []
    if kind == "text":
        return [Selected("text", word.section_id, word.role, word) for word in ctx.facts.words]
    if kind == "shape":
        return [Selected("shape", shape.section_id, shape.role, shape) for shape in ctx.facts.shapes]
    return []


def select(ctx: CheckContext, spec: dict[str, Any]) -> list[Selected]:
    sections = {section.id: section.intent for section in ctx.doc.sections if section.id is not None}
    components = {section.id: section.component for section in ctx.composition.sections} if ctx.composition else {}
    return [
        item
        for item in _selected(ctx, spec["kind"])
        if _matches(item.role, spec.get("role"))
        and _matches(sections.get(item.section_id), spec.get("section_intent"))
        and _matches(components.get(item.section_id), spec.get("component"))
    ]


def _run_sub(ctx: CheckContext, rule: Rule, sub: dict[str, Any]) -> list[Finding]:
    kind = sub["kind"]
    if kind not in CHECKS:
        raise UnknownCheckError(f"no check registered for kind {kind!r}")
    return CHECKS[kind].run(ctx, rule.model_copy(update={"check": sub}))


@register("all-of")
class AllOf:
    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        return [finding for sub in rule.check["checks"] for finding in _run_sub(ctx, rule, sub)]


@register("any-of")
class AnyOf:
    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        results = [_run_sub(ctx, rule, sub) for sub in rule.check["checks"]]
        return [finding for result in results for finding in result] if all(results) else []


@register("not")
class Not:
    def run(self, ctx: CheckContext, rule: Rule) -> list[Finding]:
        (sub,) = rule.check["checks"]
        if _run_sub(ctx, rule, sub):
            return []
        return [make_finding(rule, ctx, message=f"Check {sub['kind']} passed")]
