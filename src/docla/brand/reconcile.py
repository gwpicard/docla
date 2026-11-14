"""Reconcile stated and measured brand evidence."""

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from docla.brand.claims import CLAIMS, load_claims
from docla.brand.measure import MEASURE, MeasureSet, Stat, load_measurement
from docla.brand.pages import PAGES, load_pages
from docla.brand.questions import BrandQuestion, QuestionOption, QuestionSource, SetToken, WriteRule, add_questions
from docla.brand.templates import TemplateFacts, TemplateReport
from docla.brand.tokenmap import TOKEN_CLAIMS, load_token_claims, path_format
from docla.brand.workspace import BrandError
from docla.model import Rule
from docla.model.source import Format
from docla.theme.labels import ValueProvenance, ValueSource

Origin = Literal["guidelines", "template", "layout-pages", "examples"]
RECONCILE = Path("theme/ingest/reconcile.json")
TEMPLATES = Path("theme/ingest/templates.json")


class Candidate(BaseModel):
    value: float | int | str
    origin: Origin
    source: ValueSource
    min: float | None = None
    max: float | None = None


class Settled(BaseModel):
    path: str
    format: Format | None
    status: Literal["agreed", "single", "conflict", "proposed"]
    value: float | int | str
    provenance: ValueProvenance
    candidates: list[Candidate]
    drift: bool = False
    question: str | None = None


class ProposedRule(BaseModel):
    id: str
    title: str
    format: Format
    check: dict[str, Any]
    files: list[str]
    titles: list[str]

    def rule_data(self, status: str = "proposed") -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "origin": "ingested",
            "strength": "soft",
            "status": status,
            "severity": "warning",
            "tier": "source",
            "scope": {"format": self.format},
            "check": self.check,
            "remedy": {"class": "redraft", "hint": "Revise the title to follow the proposed rule."},
            "provenance": {
                "label": "measured",
                "source": {"files": self.files, "role": "examples", "note": f"measured over {len(self.titles)} titles"},
                "by": "brand/reconcile",
            },
        }


class Reconciliation(BaseModel):
    schema_version: int = 1
    values: list[Settled]
    proposed_rules: list[ProposedRule]
    questions: list[str]


def template_candidates(facts: TemplateFacts) -> list[tuple[str, Candidate]]:
    result: list[tuple[str, Candidate]] = []

    def add(path: str, value: float | int | str | None, where: str) -> None:
        if value is not None:
            result.append(
                (
                    path,
                    Candidate(
                        value=value,
                        origin="template",
                        source=ValueSource(file=facts.source, role="templates", note=where),
                    ),
                )
            )

    page = facts.page_model
    prefix = f"pages.{facts.format}"
    add(prefix + ".width", page.width, "page model")
    add(prefix + ".height", page.height, "page model")
    if facts.format == "doc":
        if page.margins:
            for side, value in zip(("top", "right", "bottom", "left"), page.margins, strict=True):
                add(prefix + ".margin." + side, value, "page model")
        add(prefix + ".columns", page.columns, "page model")
        add(prefix + ".gutter", page.column_gap, "page model")
    else:
        for layout in facts.layouts:
            boxes = [
                p.box
                for p in layout.placeholders
                if p.type in ("title", "center_title", "body", "object") and p.box is not None
            ]
            kinds = {p.type for p in layout.placeholders if p.box is not None}
            if kinds.intersection({"title", "center_title"}) and kinds.intersection({"body", "object"}):
                for side, value in (
                    ("left", min(b.x0 for b in boxes)),
                    ("top", min(b.y0 for b in boxes)),
                    ("right", page.width - max(b.x1 for b in boxes)),
                    ("bottom", page.height - max(b.y1 for b in boxes)),
                ):
                    add(prefix + ".margin." + side, value, layout.where)
                break
    for font in facts.fonts:
        role = {"major": "display", "minor": "text"}.get(font.role)
        if role:
            add(f"type.families.{role}.name", font.family, font.where)
    for colour in facts.colours:
        role = {"dk1": "ink", "lt1": "surface", "accent1": "accent"}.get(colour.role)
        if role:
            add(f"colour.roles.{role}", colour.hex, colour.where)
    styles = (
        {"title": "title", "body.1": "body"}
        if facts.format == "slides"
        else {"Normal": "body", "Heading 1": "h1", "Heading 2": "h2", "Caption": "caption"}
    )
    for style in facts.styles:
        if style.name in styles:
            add(f"type.scale.{facts.format}.{styles[style.name]}.size", style.size, style.where)
    return result


def _measure_candidates(item: MeasureSet, scale: float, existing: set[str]) -> list[tuple[str, Candidate]]:
    source = ValueSource(
        files=sorted({p.file for p in item.pages}),
        role="examples" if item.kind == "examples" else "guidelines",
        note=f"measured over {len(item.pages)} pages",
    )
    prefix = f"pages.{item.format}"
    stats = [(prefix + ".width", item.width), (prefix + ".height", item.height)]
    stats += [(prefix + ".margin." + side, stat) for side, stat in item.margin.items()]
    stats += [
        (f"type.scale.{item.format}.body.size", item.body_size),
        (f"type.scale.{item.format}.{'title' if item.format == 'slides' else 'h1'}.size", item.title_size),
    ]

    def candidate(stat: Stat) -> Candidate:
        return Candidate(
            value=stat.value * scale, min=stat.min * scale, max=stat.max * scale, origin=item.kind, source=source
        )

    result = [(path, candidate(stat)) for path, stat in stats]
    for role, font in (("display", item.title_font), ("text", item.body_font)):
        path = f"type.families.{role}.name"
        if font and path in existing:
            result.append((path, Candidate(value=font, origin=item.kind, source=source)))
    return result


def _agrees(path: str, winner: Candidate, other: Candidate) -> bool:
    a, b = winner.value, other.value
    if path.startswith("type.families."):

        def normal(x: float | int | str) -> str:
            return re.sub(r"[^a-z0-9]", "", str(x).lower())

        x, y = normal(a), normal(b)
        return x == y or (other.origin in ("examples", "layout-pages") and y.startswith(x))
    if isinstance(a, str) or isinstance(b, str):
        return str(a).lower() == str(b).lower()
    if path.startswith("pages.") and not path.endswith(".columns"):
        tolerance = max(1.0, 0.02 * max(abs(a), abs(b)))
        if other.min is not None and other.max is not None:
            return other.min - tolerance <= a <= other.max + tolerance
        return abs(a - b) <= tolerance
    if path.endswith((".size", ".min_size")):
        return abs(a - b) <= 0.5
    return a == b


def _evidence(brand: Path, candidates: list[Candidate]) -> list[QuestionSource]:
    crops = {(p.file, p.page): p.png for p in load_pages(brand).pages} if (brand / PAGES).exists() else {}
    result = []
    for c in candidates:
        for file in [c.source.file] if c.source.file else c.source.files:
            result.append(
                QuestionSource(
                    file=file,
                    page=c.source.page,
                    quote=c.source.quote,
                    crop=crops.get((file, c.source.page)) if c.source.page is not None else None,
                )
            )
    return result


def _label(path: str, c: Candidate) -> str:
    value = str(c.value) + (
        " pt"
        if (path.startswith("pages.") and not path.endswith(".columns")) or path.endswith((".size", ".min_size"))
        else ""
    )
    details: str = c.origin
    if c.source.page is not None:
        details += f", page {c.source.page}"
    if c.source.note and c.source.note.startswith("measured over "):
        details += ", " + c.source.note.removeprefix("measured over ")
    return f"{value} ({details})"


def _value_question(brand: Path, item: Settled) -> BrandQuestion:
    candidates = item.candidates
    if item.status == "proposed":
        return BrandQuestion(
            id=f"confirm.{item.path}",
            kind="confirm",
            format=item.format,
            blocking=False,
            text=f"Keep {_label(item.path, candidates[0])} for {item.path.replace('.', ' ')}?",
            recommended="yes",
            evidence=_evidence(brand, candidates),
            options=[
                QuestionOption(
                    id="yes",
                    label=f"Keep {item.value}",
                    effects=[SetToken(kind="set-token", path=item.path, value=item.value)],
                ),
                QuestionOption(id="no", label="Leave it open"),
            ],
        )
    distinct: list[Candidate] = []
    for c in candidates:
        if not any(c.value == previous.value for previous in distinct):
            distinct.append(c)
    return BrandQuestion(
        id=f"conflict.{item.path}",
        kind="conflict",
        format=item.format,
        blocking=any(c.origin in ("guidelines", "template") for c in candidates),
        recommended="a",
        text=f"{item.path.replace('.', ' ')}: "
        + ", ".join(_label(item.path, c) for c in candidates)
        + ". Which applies?",
        evidence=_evidence(brand, candidates),
        options=[
            QuestionOption(
                id=chr(97 + i),
                label=_label(item.path, c),
                effects=[SetToken(kind="set-token", path=item.path, value=c.value)],
            )
            for i, c in enumerate(distinct)
        ],
    )


def _rules(item: MeasureSet) -> list[ProposedRule]:
    titles = [t.text for t in item.titles]
    if item.kind != "examples" or len(titles) < 3:
        return []
    n = max(len(t.split()) for t in titles)
    files = sorted({t.file for t in item.titles})
    result = [
        ProposedRule(
            id=f"brand.{item.format}.title-words",
            title=f"Titles have at most {n} words",
            check={
                "kind": "text-pattern",
                "field": "title",
                "regex": rf"^\s*\S+(?:\s+\S+){{0,{n - 1}}}\s*$",
                "must_match": True,
            },
            format=item.format,
            files=files,
            titles=titles,
        )
    ]
    if all(not t.rstrip().endswith(".") for t in titles):
        result.append(
            ProposedRule(
                id=f"brand.{item.format}.title-no-full-stop",
                title="Titles have no full stop",
                check={"kind": "text-pattern", "field": "title", "regex": r"\.\s*$", "must_match": False},
                format=item.format,
                files=files,
                titles=titles,
            )
        )
    return result


def reconcile(brand: Path) -> Reconciliation:
    if not any((brand / p).exists() for p in (TOKEN_CLAIMS, TEMPLATES, MEASURE)):
        raise BrandError("Run docla brand tie, docla brand templates or docla brand measure first")
    grouped: dict[str, list[Candidate]] = {}

    def add(path: str, candidate: Candidate) -> None:
        grouped.setdefault(path, []).append(candidate)

    if (brand / TOKEN_CLAIMS).exists():
        for claim in sorted(load_token_claims(brand).items, key=lambda c: c.strength != "hard"):
            add(
                claim.path,
                Candidate(
                    value=claim.value,
                    origin="guidelines",
                    source=ValueSource(
                        role="guidelines", file=claim.source.file, page=claim.source.page, quote=claim.source.quote
                    ),
                ),
            )
    if (brand / TEMPLATES).exists():
        report = TemplateReport.model_validate_json((brand / TEMPLATES).read_text(encoding="utf-8"))
        for template in report.templates:
            for path, candidate in template_candidates(template):
                add(path, candidate)
    sets = load_measurement(brand).sets if (brand / MEASURE).exists() else []
    existing = set(grouped)
    for item in sorted(sets, key=lambda s: s.kind != "layout-pages"):
        width = grouped.get(f"pages.{item.format}.width", [])
        scale = (
            float(width[0].value) / item.width.value
            if item.kind == "layout-pages" and width and item.width.value
            else 1.0
        )
        for path, candidate in _measure_candidates(item, scale, existing):
            add(path, candidate)
    values: list[Settled] = []
    questions: list[BrandQuestion] = []
    for path, candidates in sorted(grouped.items()):
        winner = candidates[0]
        status: Literal["agreed", "single", "conflict", "proposed"] = (
            ("proposed" if winner.origin == "examples" else "single")
            if len(candidates) == 1
            else ("agreed" if all(_agrees(path, winner, c) for c in candidates[1:]) else "conflict")
        )
        drift = any(
            not _agrees(path, a, b)
            for a in candidates
            for b in candidates
            if a.origin == "guidelines" and b.origin == "template"
        )
        settled = Settled(
            path=path,
            format=path_format(path),
            status=status,
            value=winner.value,
            provenance=ValueProvenance(label="measured", source=winner.source),
            candidates=candidates,
            drift=drift,
        )
        if status in ("conflict", "proposed"):
            question = _value_question(brand, settled)
            settled.question = question.id
            questions.append(question)
        values.append(settled)
    if (brand / CLAIMS).exists():
        for ambiguity in load_claims(brand).claims:
            if ambiguity.kind == "ambiguity":
                candidates = [
                    Candidate(
                        value=ambiguity.statement,
                        origin="guidelines",
                        source=ValueSource(file=s.file, page=s.page, quote=s.quote, role="guidelines"),
                    )
                    for s in ambiguity.sources
                ]
                questions.append(
                    BrandQuestion(
                        id=f"ambiguity.{ambiguity.id}",
                        kind="conflict",
                        text=ambiguity.statement,
                        blocking=True,
                        evidence=_evidence(brand, candidates),
                    )
                )
    rules = sorted((r for s in sets for r in _rules(s)), key=lambda r: r.id)
    for rule in rules:
        questions.append(
            BrandQuestion(
                id=f"confirm.rule.{rule.id}",
                kind="confirm",
                text=f"{rule.title}?",
                format=rule.format,
                blocking=False,
                recommended="yes",
                options=[
                    QuestionOption(
                        id="yes",
                        label="Keep the rule",
                        effects=[
                            WriteRule(kind="write-rule", rule=Rule.model_validate(rule.rule_data(status="active")))
                        ],
                    ),
                    QuestionOption(id="no", label="Leave it open"),
                ],
            )
        )
    add_questions(brand, questions)
    result = Reconciliation(values=values, proposed_rules=rules, questions=[q.id for q in questions])
    output = brand / RECONCILE
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def load_reconciliation(brand: Path) -> Reconciliation:
    path = brand / RECONCILE
    if not path.exists():
        raise BrandError("Run docla brand reconcile first")
    return Reconciliation.model_validate_json(path.read_text(encoding="utf-8"))
