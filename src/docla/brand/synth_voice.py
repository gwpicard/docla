"""Draft voice and required elements from cited brand material."""

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from docla.agents.client import Claude
from docla.brand.claims import CLAIMS, load_claims, normalise
from docla.brand.intake import MANIFEST
from docla.brand.pages import load_manifest
from docla.brand.questions import BrandQuestion, add_questions
from docla.model.source import Format
from docla.theme import ThemeError, load_theme, neutral_theme
from docla.theme.labels import ValueProvenance, ValueSource
from docla.theme.required import RequiredElement, RequiredKind, load_required
from docla.theme.voice import Term, Voice, load_voice


class TermDraft(BaseModel):
    term: str
    source_id: str


class PairDraft(BaseModel):
    preferred: str
    avoid: list[str]
    source_id: str


class RequiredDraft(BaseModel):
    element: RequiredKind
    name: str
    text: str | None
    place: str | None
    formats: list[Format]
    source_id: str


class VoiceReply(BaseModel):
    summary_slides: str | None
    summary_doc: str | None
    banned: list[TermDraft]
    terminology: list[PairDraft]
    required: list[RequiredDraft]


class VoiceSynthesis(BaseModel):
    banned: list[str]
    terminology: list[Term]
    required: list[str]
    dropped: list[dict[str, str]]
    questions: list[str]


def _sources(brand: Path) -> tuple[list[dict[str, Any]], dict[str, tuple[str, ValueSource]]]:
    rows: list[dict[str, Any]] = []
    sources: dict[str, tuple[str, ValueSource]] = {}
    if (brand / CLAIMS).exists():
        for claim in load_claims(brand).claims:
            if (
                claim.topic not in ("voice-tone", "dos-donts", "legal-mandatory")
                or claim.kind == "token"
                or claim.illustrative
            ):
                continue
            quotes = [source.quote for source in claim.sources]
            rows.append({"id": claim.id, "statement": claim.statement, "quotes": quotes})
            first = claim.sources[0]
            sources[claim.id] = (
                " ".join(quotes),
                ValueSource(file=first.file, page=first.page, quote=first.quote, role="guidelines"),
            )
    if (brand / MANIFEST).exists():
        for entry in load_manifest(brand).files:
            if entry.role == "notes" and entry.type in ("md", "txt"):
                text = (brand / entry.path).read_text(encoding="utf-8")
                ident = f"note:{entry.path}"
                rows.append({"id": ident, "text": text})
                sources[ident] = (text, ValueSource(file=entry.path, quote=text.strip(), role="notes"))
    return rows, sources


def _ground(
    item: str,
    source_id: str,
    sources: dict[str, tuple[str, ValueSource]],
    dropped: list[dict[str, str]],
    *,
    word: bool = False,
) -> bool:
    source = sources.get(source_id)
    target = normalise(item)
    found = bool(
        source
        and target
        and (
            re.search(r"(?<!\w)" + re.escape(target) + r"(?!\w)", normalise(source[0]))
            if word
            else target in normalise(source[0])
        )
    )
    if not found:
        dropped.append(
            {"item": item, "source_id": source_id, "reason": "not in source" if source else "unknown source"}
        )
    return found


def _assemble(
    reply: VoiceReply, sources: dict[str, tuple[str, ValueSource]]
) -> tuple[Voice, list[RequiredElement], VoiceSynthesis, dict[str, Any], list[BrandQuestion]]:
    dropped: list[dict[str, str]] = []
    kept: dict[str, Any] = {"banned": [], "terminology": [], "required": []}
    banned = set()
    for draft in reply.banned:
        if _ground(draft.term, draft.source_id, sources, dropped, word=True):
            banned.add(draft.term.lower())
            kept["banned"].append(draft.model_dump())
    terms: dict[str, Term] = {}
    for draft in reply.terminology:
        valid = _ground(draft.preferred, draft.source_id, sources, dropped, word=True)
        avoid = [word for word in draft.avoid if _ground(word, draft.source_id, sources, dropped, word=True)]
        if valid and avoid:
            term = terms.setdefault(draft.preferred, Term(preferred=draft.preferred, avoid=[]))
            term.avoid.extend(word for word in avoid if word not in term.avoid)
            kept["terminology"].append(draft.model_dump())
    required: list[RequiredElement] = []
    questions: list[BrandQuestion] = []
    for draft in reply.required:
        if draft.source_id not in sources:
            _ground(draft.text or draft.name, draft.source_id, sources, dropped)
            continue
        if draft.text is not None and not _ground(draft.text, draft.source_id, sources, dropped):
            continue
        count = sum(item.element == draft.element for item in required) + 1
        ident = draft.element + (f"-{count}" if count > 1 else "")
        required.append(
            RequiredElement(
                id=ident,
                **draft.model_dump(exclude={"source_id"}),
                provenance=ValueProvenance(label="measured", source=sources[draft.source_id][1]),
            )
        )
        kept["required"].append({"id": ident, "source_id": draft.source_id})
        if draft.element in ("disclaimer", "confidentiality") and not draft.text:
            questions.append(
                BrandQuestion(
                    id=f"required.{ident}",
                    kind="rule",
                    blocking=False,
                    format=draft.formats[0] if len(draft.formats) == 1 else None,
                    text=f"What is the exact text for {draft.name}?",
                )
            )
    neutral = load_voice(neutral_theme())
    voice = Voice(
        banned=sorted(banned),
        terminology=list(terms.values()),
        summary={
            "slides": reply.summary_slides or neutral.summary.get("slides", ""),
            "doc": reply.summary_doc or neutral.summary.get("doc", ""),
        },
    )
    result = VoiceSynthesis(
        banned=voice.banned,
        terminology=voice.terminology,
        required=[item.id for item in required],
        dropped=dropped,
        questions=[q.id for q in questions],
    )
    return voice, required, result, kept, questions


def _save(
    brand: Path, voice: Voice, required: list[RequiredElement], result: VoiceSynthesis, kept: dict[str, Any]
) -> None:
    root = brand / "theme"
    paths = [root / "voice/terminology.yaml", root / "required.yaml", root / "ingest/voice.json"]
    old = {path: path.read_bytes() if path.exists() else None for path in paths}
    try:
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
        paths[0].write_text(
            yaml.safe_dump(voice.model_dump(mode="json"), sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        paths[1].write_text(
            yaml.safe_dump(
                {"elements": [item.model_dump(mode="json", exclude_none=True) for item in required]},
                sort_keys=False,
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        paths[2].write_text(
            json.dumps({**result.model_dump(mode="json"), "sources": kept}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        theme = load_theme(root)
        load_voice(theme)
        load_required(theme)
    except ThemeError:
        for path, content in old.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise


async def synthesise_voice(brand: Path, claude: Claude) -> VoiceSynthesis:
    rows, sources = _sources(brand)
    if rows:
        prompt = files("docla.brand.prompts").joinpath("voice.txt").read_text(encoding="utf-8")
        reply = await claude.call(
            "brand.synthesise",
            VoiceReply,
            system=[{"type": "text", "text": prompt}],
            content=[{"type": "text", "text": json.dumps(rows)}],
            effort="medium",
            max_tokens=8000,
        )
    else:
        reply = VoiceReply(summary_slides=None, summary_doc=None, banned=[], terminology=[], required=[])
    voice, required, result, kept, questions = _assemble(reply, sources)
    if not rows:
        voice = load_voice(neutral_theme())
        result.banned, result.terminology = voice.banned, voice.terminology
    _save(brand, voice, required, result, kept)
    if questions:
        add_questions(brand, questions)
    return result
