"""Tie stated claims to grounded theme token values."""

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel

from docla.agents.client import Claude
from docla.brand.claims import Claim, VerifiedSource, load_claims, normalise
from docla.brand.workspace import BrandError
from docla.model.source import Format
from docla.theme import neutral_theme
from docla.theme.models import to_pt

TOKEN_CLAIMS = Path("theme/ingest/token-claims.json")


class TokenTie(BaseModel):
    claim_id: str
    path: str
    value: str
    reason: str


class TokenTieReply(BaseModel):
    ties: list[TokenTie]


class TokenClaim(BaseModel):
    path: str
    value: float | int | str
    format: Format | None
    claim_id: str
    strength: Literal["hard", "soft"]
    source: VerifiedSource
    reason: str


class RefusedTie(BaseModel):
    claim_id: str
    path: str
    value: str
    reason: str


class TokenClaims(BaseModel):
    schema_version: int = 1
    items: list[TokenClaim]
    refused: list[RefusedTie]
    untied: list[str]


def token_targets() -> list[str]:
    tokens = neutral_theme().tokens
    targets = [f"colour.roles.{role}" for role in tokens.colour.roles]
    targets += ["colour.contrast_min", "type.families.display.name", "type.families.text.name", "imagery.min_dpi"]
    for fmt, scale in tokens.type.scale.items():
        targets.append(f"type.scale.{fmt}.min_size")
        targets.extend(
            f"type.scale.{fmt}.{role}.{field}" for role in scale.roles for field in ("size", "weight", "leading")
        )
    for fmt in tokens.pages:
        targets.extend(f"pages.{fmt}.{field}" for field in ("width", "height"))
        targets.extend(f"pages.{fmt}.margin.{side}" for side in ("top", "right", "bottom", "left"))
    targets.extend(["pages.doc.columns", "pages.doc.gutter"])
    return sorted(targets)


def path_format(path: str) -> Format | None:
    parts = path.split(".")
    if parts[0] == "pages" and len(parts) > 1:
        return cast(Format, parts[1])
    if parts[:2] == ["type", "scale"] and len(parts) > 2:
        return cast(Format, parts[2])
    return None


def _parse_value(path: str, value: str) -> float | int | str:
    value = value.strip()
    if path.startswith("colour.roles."):
        if not re.fullmatch(r"#?[0-9a-fA-F]{6}", value):
            raise ValueError
        return "#" + value.lstrip("#").upper()
    if path.startswith("type.families."):
        if not value:
            raise ValueError
        return value
    if path.endswith((".weight", ".columns", ".min_dpi")):
        if not re.fullmatch(r"[+-]?\d+", value):
            raise ValueError
        return int(value)
    if path.endswith((".leading", ".contrast_min")):
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
            raise ValueError
        return float(value)
    compact = re.sub(r"\s+", "", value)
    if re.fullmatch(r"-?\d+(?:\.\d+)?", compact):
        return to_pt(float(compact))
    return to_pt(compact)


def _grounded(tie: TokenTie, claim: Claim) -> bool:
    texts = [item.value for item in claim.values]
    if any(source.found != "visual" for source in claim.sources):
        texts.extend(source.quote for source in claim.sources)
    haystack = normalise(" ".join(texts))
    if tie.path.startswith("colour.roles."):
        return tie.value.strip().lstrip("#").casefold() in haystack
    if tie.path.startswith("type.families."):
        return normalise(tie.value) in haystack
    number = re.search(r"[+-]?\d+(?:\.\d+)?", tie.value)
    return bool(number and number.group() in re.findall(r"[+-]?\d+(?:\.\d+)?", haystack))


def check_tie(tie: TokenTie, claim: Claim | None) -> TokenClaim | str:
    if claim is None or tie.claim_id != claim.id:
        return "unknown claim"
    if tie.path not in token_targets():
        return "unknown token"
    fmt = path_format(tie.path)
    if fmt is not None and claim.formats and fmt not in claim.formats:
        return "wrong format"
    try:
        value = _parse_value(tie.path, tie.value)
    except ValueError:
        return "bad value"
    if not _grounded(tie, claim):
        return "value not in claim"
    return TokenClaim(
        path=tie.path,
        value=value,
        format=fmt,
        claim_id=claim.id,
        strength=claim.strength,
        source=claim.sources[0],
        reason=tie.reason,
    )


def _claim_data(claim: Claim) -> dict[str, object]:
    return {
        "id": claim.id,
        "kind": claim.kind,
        "statement": claim.statement,
        "values": [value.model_dump() for value in claim.values],
        "formats": claim.formats,
        "quotes": [source.quote for source in claim.sources],
    }


async def tie_claims(brand: Path, claude: Claude, *, batch_size: int = 30) -> TokenClaims:
    candidates = [
        c for c in load_claims(brand).claims if c.kind in ("token", "rule") and c.values and not c.illustrative
    ]
    by_id = {claim.id: claim for claim in candidates}
    prompt = files("docla.brand.prompts").joinpath("tokens.txt").read_text(encoding="utf-8")
    items: dict[tuple[str, str], TokenClaim] = {}
    refused: list[RefusedTie] = []
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        reply = await claude.call(
            "brand.extract",
            TokenTieReply,
            system=[{"type": "text", "text": prompt}],
            content=[
                {"type": "text", "text": "\n".join(token_targets())},
                {"type": "text", "text": json.dumps([_claim_data(c) for c in batch])},
            ],
            effort="medium",
            max_tokens=8000,
        )
        for tie in reply.ties:
            checked = check_tie(tie, by_id.get(tie.claim_id))
            if isinstance(checked, str):
                refused.append(RefusedTie(claim_id=tie.claim_id, path=tie.path, value=tie.value, reason=checked))
            else:
                items.setdefault((checked.path, checked.claim_id), checked)
    tied = {item.claim_id for item in items.values()}
    result = TokenClaims(
        items=sorted(items.values(), key=lambda i: (i.path, i.claim_id)),
        refused=refused,
        untied=sorted(c.id for c in candidates if c.kind == "token" and c.id not in tied),
    )
    path = brand / TOKEN_CLAIMS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def load_token_claims(brand: Path) -> TokenClaims:
    path = brand / TOKEN_CLAIMS
    if not path.exists():
        raise BrandError("Run docla brand tie first")
    return TokenClaims.model_validate_json(path.read_text(encoding="utf-8"))
