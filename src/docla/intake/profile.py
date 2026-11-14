"""Build an evidenced intake brief from tables and doctype defaults."""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from docla.agents.gatherer import Fact, with_fact_ids
from docla.doctypes import Doctype
from docla.model.brief import (
    BRIEF_FIELDS,
    Audience,
    Brief,
    BriefField,
    BriefScope,
    FieldProvenance,
    FieldStatus,
    Length,
    Metric,
    RequiredElement,
    Topic,
)
from docla.model.source import Format
from docla.sources import Extracted
from docla.tables import TableCell, read_cells, sheet_locator, table_facts


class ReadBackItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: BriefField
    text: str
    status: FieldStatus
    evidence: list[str]
    sources: list[str]


class Conflict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: BriefField
    label: str
    header: str
    values: list[str]
    evidence: list[str]
    sources: list[str]


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: Brief
    read_back: list[ReadBackItem]
    conflicts: list[Conflict]
    facts: list[Fact]
    files: list[str]


Pair = tuple[TableCell, Fact]


def _id(fact: Fact) -> str:
    assert fact.id is not None
    return fact.id


def _sources(evidence: list[str], facts: list[Fact]) -> list[str]:
    lookup = {_id(fact): f"{fact.source_key} {fact.locator}" for fact in facts}
    return [lookup[item] for item in evidence if item in lookup]


def _fill(result: Profile, field: BriefField, value: Any, status: FieldStatus, evidence: list[str], text: str) -> None:
    if result.brief.status(field) is not None:
        return
    setattr(result.brief, field, value)
    result.brief.provenance[field] = FieldProvenance(status=status, evidence=evidence)
    result.read_back.append(
        ReadBackItem(field=field, text=text, status=status, evidence=evidence, sources=_sources(evidence, result.facts))
    )


def _scope(result: Profile, pairs: list[Pair]) -> None:
    dates = [(cell, fact) for cell, fact in pairs if cell.value.kind == "date" and cell.value.date is not None]
    currencies = [(cell, fact) for cell, fact in pairs if cell.value.kind == "currency"]
    if not dates and not currencies:
        return
    evidence: list[str] = []
    period = None
    if dates:
        ordered = sorted(dates, key=lambda pair: pair[0].value.date.isoformat())  # type: ignore[union-attr]
        first, last = ordered[0], ordered[-1]
        start, end = first[0].value.date, last[0].value.date
        assert start is not None and end is not None
        quarter = (start.month - 1) // 3 + 1
        period = (
            f"Q{quarter} {start.year}"
            if start.year == end.year and quarter == (end.month - 1) // 3 + 1
            else f"{start.isoformat()} to {end.isoformat()}"
        )
        evidence.append(_id(first[1]))
        if first[1].id != last[1].id:
            evidence.append(_id(last[1]))
    codes = {cell.value.currency for cell, _ in currencies}
    currency = next(iter(codes)) if len(codes) == 1 else None
    if currency is not None:
        evidence.append(_id(currencies[0][1]))
    if not evidence:
        return
    parts = ([f"Period: {period}"] if period else []) + ([f"currency: {currency}"] if currency else [])
    _fill(result, "scope", BriefScope(period=period, currency=currency), "inferred", evidence, "; ".join(parts))


def _groups(pairs: list[Pair], attribute: str) -> dict[str, list[Pair]]:
    groups: dict[str, list[Pair]] = {}
    for cell, fact in pairs:
        name = getattr(cell, attribute)
        if name and cell.value.kind in {"number", "percent", "currency"}:
            groups.setdefault(name, []).append((cell, fact))
    return groups


def _range(pairs: list[Pair]) -> str:
    first = pairs[0][0]
    # A sheet name can recur in another file, so source identity also matters.
    same = [cell for cell, fact in pairs if cell.sheet == first.sheet and fact.source_key == pairs[0][1].source_key]
    cells = first.cell if len(same) == 1 else f"{first.cell}:{same[-1].cell}"
    return sheet_locator(first.sheet, cells)


def _summaries(result: Profile, pairs: list[Pair]) -> None:
    topics = _groups(pairs, "label")
    if topics:
        _fill(
            result,
            "topics",
            [Topic(name=name, data_ref=_range(group)) for name, group in topics.items()],
            "inferred",
            [_id(group[0][1]) for group in topics.values()],
            f"Topics: {', '.join(topics)}",
        )
    metrics = _groups(pairs, "header")
    if metrics:
        _fill(
            result,
            "metrics",
            [Metric(name=name, sources=[_range(group)]) for name, group in metrics.items()],
            "inferred",
            [_id(group[0][1]) for group in metrics.values()],
            f"Measures: {', '.join(metrics)}",
        )


def _conflicts(result: Profile, pairs: list[Pair]) -> None:
    groups: dict[tuple[str, str], list[Pair]] = {}
    for cell, fact in pairs:
        if cell.label and cell.header and cell.value.kind in {"number", "percent", "currency", "date"}:
            groups.setdefault((cell.label, cell.header), []).append((cell, fact))
    for (label, header), group in groups.items():
        if len({cell.value.text for cell, _ in group}) < 2:
            continue
        evidence = [_id(fact) for _, fact in group]
        result.conflicts.append(
            Conflict(
                field="metrics",
                label=label,
                header=header,
                values=[cell.value.text for cell, _ in group],
                evidence=evidence,
                sources=_sources(evidence, result.facts),
            )
        )


def _defaults(result: Profile, doctype: Doctype) -> None:
    source = f"doctype:{doctype.name}"
    evidence = [source]
    _fill(result, "doctype", doctype.name, "defaulted", evidence, f"Document type: {doctype.name}")
    _fill(result, "audience", Audience(who=doctype.audience), "defaulted", evidence, f"Audience: {doctype.audience}")
    if doctype.default_length is not None:
        _fill(
            result,
            "length",
            Length(count=doctype.default_length),
            "defaulted",
            evidence,
            f"Length: about {doctype.default_length} {result.brief.length_unit()}",
        )
    if doctype.required_fields:
        _fill(
            result,
            "required_elements",
            [RequiredElement(element=f.key, source=source) for f in doctype.required_fields],
            "defaulted",
            evidence,
            f"Required: {', '.join(f.label for f in doctype.required_fields)}",
        )


def profile(
    sources: Sequence[Extracted],
    *,
    fmt: Format,
    doctype: Doctype | None = None,
    request: str = "",
    brief: Brief | None = None,
) -> Profile:
    if brief is not None and brief.format != fmt:
        raise ValueError("Brief format does not match requested format")
    result = Profile(
        brief=brief.model_copy(deep=True) if brief is not None else Brief(format=fmt, request=request),
        read_back=[],
        conflicts=[],
        facts=[],
        files=[],
    )
    pairs: list[Pair] = []
    for source in sources:
        if source.kind != "table":
            result.files.append(source.name)
            continue
        cells = read_cells(source.source)
        facts = with_fact_ids(table_facts(source.source, source.key))
        result.facts.extend(facts)
        pairs.extend(zip(cells, facts, strict=True))
    if doctype is not None:
        _defaults(result, doctype)
    _scope(result, pairs)
    _summaries(result, pairs)
    _conflicts(result, pairs)
    result.read_back.sort(key=lambda item: BRIEF_FIELDS.index(item.field))
    return result
