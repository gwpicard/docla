"""Turn guideline claims into validated rules and visual questions."""

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

from docla.agents.client import Claude
from docla.brand.claims import Claim, load_claims
from docla.brand.questions import (
    BrandQuestion,
    QuestionOption,
    QuestionSource,
    WriteRule,
    add_questions,
    load_questions,
)
from docla.brand.reconcile import RECONCILE, load_reconciliation
from docla.brand.workspace import BrandError
from docla.model import Rule
from docla.theme import ThemeError, load_theme, neutral_theme
from docla.theme.rubric import load_rubric
from docla.theme.rules import _check_kind, load_theme_rules

BRAND_CHECK_KINDS = ("text-pattern", "all-of", "any-of", "not")


class RuleDraft(BaseModel):
    claim_id: str
    title: str
    tier: Literal["source", "geometry", "pixel", "semantic"]
    severity: Literal["error", "warning", "info"]
    check_json: str | None
    question: str | None
    remedy_class: Literal["redraft", "restructure", "tune", "engine", "report", "ask"]
    remedy_hint: str


class RuleDraftReply(BaseModel):
    drafts: list[RuleDraft]


class RuleSynthesis(BaseModel):
    rules: list[str]
    rubric: list[str]
    questions: list[str]


def valid_check(check: Any) -> str | None:
    if not isinstance(check, dict) or check.get("kind") not in BRAND_CHECK_KINDS:
        return "unknown or missing check kind"
    try:
        _check_kind(check)
        if check["kind"] == "text-pattern":
            if check.get("field") not in ("title", "paragraphs", "items") or not isinstance(
                check.get("must_match"), bool
            ):
                return "invalid text-pattern parameters"
            if not isinstance(check.get("regex"), str):
                return "invalid regex"
            re.compile(check["regex"])
        else:
            for child in check["checks"]:
                reason = valid_check(child)
                if reason:
                    return reason
    except (ValueError, re.error) as error:
        return str(error)
    return None


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].rstrip("-") or "rule"


def _unique(base: str, used: set[str]) -> str:
    result = base
    n = 2
    while result in used:
        result = f"{base}-{n}"
        n += 1
    used.add(result)
    return result


def _source(claim: Claim) -> dict[str, Any]:
    source = claim.sources[0]
    return {"file": source.file, "page": source.page, "quote": source.quote, "role": "guidelines"}


def _evidence(claim: Claim) -> list[QuestionSource]:
    return [QuestionSource(file=s.file, page=s.page, quote=s.quote) for s in claim.sources]


def _draft_check(draft: RuleDraft) -> Any:
    try:
        return json.loads(draft.check_json or "null")
    except (ValueError, TypeError):
        return None


async def synthesise_rules(brand: Path, claude: Claude, *, batch_size: int = 20) -> RuleSynthesis:
    theme = brand / "theme"
    info = yaml.safe_load((theme / "theme.yaml").read_text())
    if not info.get("labelled"):
        raise BrandError("The theme must be labelled before synthesising rules")
    answers = {q.id: q for q in load_questions(brand)}
    claims = [
        c
        for c in load_claims(brand).claims
        if c.kind in ("rule", "forbidden", "recommended")
        and (
            not c.illustrative
            or (f"claim.illustrative.{c.id}" in answers and answers[f"claim.illustrative.{c.id}"].option == "rule")
        )
    ]
    drafts: dict[str, RuleDraft] = {}
    prompt = files("docla.brand.prompts").joinpath("rules.txt").read_text(encoding="utf-8")
    for start in range(0, len(claims), batch_size):
        batch = claims[start : start + batch_size]
        rows = [
            {
                "id": c.id,
                "topic": c.topic,
                "kind": c.kind,
                "statement": c.statement,
                "strength": c.strength,
                "formats": c.formats,
                "quotes": [s.quote for s in c.sources],
                "check_hint": c.check_hint,
            }
            for c in batch
        ]
        reply = await claude.call(
            "brand.synthesise",
            RuleDraftReply,
            system=[{"type": "text", "text": prompt}],
            content=[{"type": "text", "text": json.dumps(rows)}],
            effort="medium",
            max_tokens=16000,
        )
        ids = {c.id for c in batch}
        for draft in reply.drafts:
            if draft.claim_id in ids:
                drafts.setdefault(draft.claim_id, draft)
    return _write(brand, claims, drafts, answers)


def _write(
    brand: Path, claims: list[Claim], drafts: dict[str, RuleDraft], answers: dict[str, BrandQuestion]
) -> RuleSynthesis:
    theme = brand / "theme"
    directory = theme / "rules/ingested"
    directory.mkdir(parents=True, exist_ok=True)
    old = {p: p.read_bytes() for p in directory.glob("*.yaml")}
    preserved = {
        p.stem: data
        for p, data in old.items()
        if (yaml.safe_load(data) or {}).get("provenance", {}).get("label") == "answered"
    }
    rules: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    labels: dict[str, Any] = {}
    questions: list[BrandQuestion] = []
    used_rules: set[str] = set()
    used_items: set[str] = set()
    for claim in claims:
        draft = drafts.get(claim.id)
        if draft is None:
            questions.append(
                BrandQuestion(
                    id=f"rule.unplaced.{claim.id}",
                    kind="rule",
                    blocking=False,
                    text=f'Could not place the claim: "{claim.statement}"',
                    evidence=_evidence(claim),
                )
            )
            continue
        check = _draft_check(draft)
        remedy = {"class": draft.remedy_class, "hint": draft.remedy_hint}
        source = _source(claim)
        label = {"label": "measured", "source": source}
        if claim.kind != "recommended" and draft.tier != "semantic" and valid_check(check) is None:
            ident = _unique(f"brand.{claim.topic}.{_slug(draft.title)}", used_rules)
            rule = {
                "id": ident,
                "title": draft.title,
                "origin": "ingested",
                "strength": claim.strength,
                "status": "active",
                "severity": draft.severity,
                "tier": draft.tier,
                "scope": {"format": claim.formats[0]} if len(claim.formats) == 1 else {},
                "check": check,
                "remedy": remedy,
                "provenance": {**label, "by": "brand/synthesise"},
            }
            rules[ident] = rule
            if claim.strength == "hard" and claim.confidence < 0.6:
                questions.append(
                    BrandQuestion(
                        id=f"rule.confirm.{ident}",
                        kind="rule",
                        text=f"Keep {draft.title}?",
                        evidence=_evidence(claim),
                        recommended="keep",
                        options=[
                            QuestionOption(id="keep", label="Keep"),
                            QuestionOption(
                                id="soften",
                                label="Soften",
                                effects=[
                                    WriteRule(kind="write-rule", rule=Rule.model_validate({**rule, "strength": "soft"}))
                                ],
                            ),
                        ],
                    )
                )
        else:
            ident = _unique(f"sem.{claim.topic}-{_slug(draft.title)}", used_items)
            items.append(
                {
                    "id": ident,
                    "question": draft.question or f"Does the page follow the brand's rule: {claim.statement}?",
                    "applies": {"formats": claim.formats} if len(claim.formats) == 1 else {},
                    "severity": draft.severity,
                    "remedy": remedy,
                }
            )
            labels[ident] = label
    if (brand / RECONCILE).exists():
        for proposed in load_reconciliation(brand).proposed_rules:
            answer = answers.get(f"confirm.rule.{proposed.id}")
            if not answer or answer.answer is None:
                rules[proposed.id] = proposed.rule_data(status="proposed")
    return _save(brand, rules, items, labels, questions, old, preserved)


def _save(
    brand: Path,
    rules: dict[str, Any],
    items: list[dict[str, Any]],
    labels: dict[str, Any],
    questions: list[BrandQuestion],
    old: dict[Path, bytes],
    preserved: dict[str, bytes],
) -> RuleSynthesis:
    theme = brand / "theme"
    directory = theme / "rules/ingested"
    rubric_path = theme / "rubric/visual.yaml"
    prov_path = theme / "provenance.yaml"
    previous = {p: p.read_bytes() if p.exists() else None for p in (rubric_path, prov_path)}
    neutral = yaml.safe_load((neutral_theme().root / "rubric/visual.yaml").read_text())["items"]
    for item in neutral:
        labels[item["id"]] = {"label": "inferred", "source": {"note": "docla's generic rubric item"}}
    provenance = yaml.safe_load(prov_path.read_text()) or {}
    provenance["rubric"] = dict(sorted(labels.items()))
    try:
        for path in old:
            path.unlink()
        for ident, rule in sorted(rules.items()):
            if ident not in preserved:
                (directory / f"{ident}.yaml").write_text(yaml.safe_dump(rule, sort_keys=False, allow_unicode=True))
        for ident, data in preserved.items():
            (directory / f"{ident}.yaml").write_bytes(data)
        rubric_path.parent.mkdir(parents=True, exist_ok=True)
        rubric_path.write_text(
            yaml.safe_dump(
                {"items": sorted(items, key=lambda i: i["id"]) + neutral}, sort_keys=False, allow_unicode=True
            )
        )
        prov_path.write_text(yaml.safe_dump(provenance, sort_keys=False, allow_unicode=True))
        loaded = load_theme(theme)
        load_theme_rules(loaded)
        load_rubric(loaded)
    except ThemeError:
        for path in directory.glob("*.yaml"):
            path.unlink()
        for path, data in old.items():
            path.write_bytes(data)
        for path, prior_data in previous.items():
            if prior_data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(prior_data)
        raise
    add_questions(brand, questions)
    return RuleSynthesis(
        rules=sorted(set(rules) | set(preserved)),
        rubric=sorted(i["id"] for i in items),
        questions=[q.id for q in questions],
    )
