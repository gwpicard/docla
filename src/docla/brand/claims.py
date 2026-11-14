"""Extract and verify claims against guideline pages."""

import hashlib
import re
import unicodedata
from importlib.resources import files
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel

from docla.agents.client import Claude
from docla.brand.agents import page_blocks
from docla.brand.pages import PageEntry, load_pages
from docla.brand.segment import Topic, load_topics, topic_groups
from docla.brand.workspace import BrandError
from docla.model.source import Format

ClaimKind = Literal["token", "rule", "ambiguity", "forbidden", "recommended"]
CLAIMS = Path("theme/ingest/claims.json")


class ClaimValue(BaseModel):
    name: str
    value: str


class ClaimSource(BaseModel):
    file: str
    page: int
    quote: str
    visual: bool = False
    bbox: list[float] | None = None


class ExtractedClaim(BaseModel):
    kind: ClaimKind
    statement: str
    values: list[ClaimValue]
    strength: Literal["hard", "soft"]
    formats: list[Format]
    sources: list[ClaimSource]
    confidence: float
    check_hint: str | None = None
    basis: Literal["stated", "shown"] = "stated"


class ExtractReply(BaseModel):
    claims: list[ExtractedClaim]


class VerifiedSource(ClaimSource):
    found: Literal["text", "visual"]


class Claim(BaseModel):
    id: str
    topic: Topic
    kind: ClaimKind
    statement: str
    values: list[ClaimValue]
    strength: Literal["hard", "soft"]
    formats: list[Format]
    sources: list[VerifiedSource]
    confidence: float
    check_hint: str | None = None
    basis: Literal["stated", "shown"] = "stated"
    illustrative: bool = False
    illustrative_reason: Literal["shown", "image"] | None = None


class DroppedClaim(BaseModel):
    topic: Topic
    statement: str
    sources: list[ClaimSource]
    reason: str


class ClaimSet(BaseModel):
    schema_version: int = 1
    claims: list[Claim]
    dropped: list[DroppedClaim]


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    replacements: dict[int, str | int | None] = {
        **dict.fromkeys(range(0x2018, 0x201C), "'"),
        **dict.fromkeys(range(0x201C, 0x2020), '"'),
        **dict.fromkeys(range(0x2010, 0x2016), "-"),
        0x2212: "-",
        0x00AD: None,
    }
    return " ".join(text.translate(str.maketrans(replacements)).split()).casefold()


def _valid_box(source: ClaimSource, page: PageEntry) -> bool:
    box = source.bbox
    return bool(box and len(box) == 4 and 0 <= box[0] < box[2] <= page.width and 0 <= box[1] < box[3] <= page.height)


def _values_found(claim: ExtractedClaim) -> bool:
    quotes = " ".join(source.quote for source in claim.sources)
    numbers = set(re.findall(r"\d+(?:\.\d+)?", quotes))
    for item in claim.values:
        value = item.value
        if re.fullmatch(r"#?[0-9A-Fa-f]{6}", value):
            if value.lstrip("#").casefold() not in quotes.casefold():
                return False
        elif any(number not in numbers for number in re.findall(r"\d+(?:\.\d+)?", value)):
            return False
    return True


def verify(claim: ExtractedClaim, sent: dict[tuple[str, int], PageEntry]) -> tuple[list[VerifiedSource], str | None]:
    if not claim.sources:
        return [], "no source"
    verified: list[VerifiedSource] = []
    for source in claim.sources:
        page = sent.get((source.file, source.page))
        if page is None:
            return [], "page not sent"
        quote = normalise(source.quote)
        found: Literal["text", "visual"]
        if quote and quote in normalise(page.text):
            found = "text"
        elif source.visual:
            if not quote or not _valid_box(source, page):
                return [], "visual source without a valid box"
            found = "visual"
        else:
            return [], "quote not found"
        verified.append(VerifiedSource(**source.model_dump(), found=found))
    if not any(source.found == "visual" for source in verified) and not _values_found(claim):
        return [], "value not in quote"
    return verified, None


def claim_id(topic: Topic, kind: ClaimKind, statement: str, sources: list[ClaimSource]) -> str:
    parts = [topic, kind, normalise(statement), *(f"{source.file}:{source.page}" for source in sources)]
    return "c-" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


async def extract_claims(brand: Path, claude: Claude, *, batch_size: int = 8) -> ClaimSet:
    from docla.brand.illustrative import mark_illustrative

    groups = topic_groups(load_topics(brand))
    index = load_pages(brand)
    pages = {(page.file, page.page): page for page in index.pages if page.role == "guidelines"}
    prompt = files("docla.brand.prompts").joinpath("extract.txt").read_text(encoding="utf-8")
    result = ClaimSet(claims=[], dropped=[])
    seen: set[str] = set()
    for topic in get_args(Topic):
        entries = [pages[key] for key in groups.get(topic, []) if key in pages]
        for start in range(0, len(entries), batch_size):
            batch = entries[start : start + batch_size]
            content = [{"type": "text", "text": f"TOPIC: {topic}"}]
            for page in batch:
                content.extend(page_blocks(page, brand))
            reply = await claude.call(
                "brand.extract",
                ExtractReply,
                system=[{"type": "text", "text": prompt}],
                content=content,
                effort="medium",
            )
            sent = {(page.file, page.page): page for page in batch}
            for extracted in reply.claims:
                sources, reason = verify(extracted, sent)
                if reason is not None:
                    result.dropped.append(
                        DroppedClaim(
                            topic=topic, statement=extracted.statement, sources=extracted.sources, reason=reason
                        )
                    )
                    continue
                identifier = claim_id(topic, extracted.kind, extracted.statement, extracted.sources)
                if identifier not in seen:
                    seen.add(identifier)
                    result.claims.append(
                        Claim(**extracted.model_dump(exclude={"sources"}), id=identifier, topic=topic, sources=sources)
                    )
    result.claims = mark_illustrative(result.claims, index)
    path = brand / CLAIMS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def load_claims(brand: Path) -> ClaimSet:
    path = brand / CLAIMS
    if not path.exists():
        raise BrandError("Run docla brand extract first")
    return ClaimSet.model_validate_json(path.read_text(encoding="utf-8"))
