"""Record approved departures from sourced theme tokens."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

from docla.brand.workspace import BrandError
from docla.model.source import Format
from docla.theme import ThemeError, load_theme
from docla.theme.labels import ValueProvenance, token_label, token_paths
from docla.theme.models import to_pt

DEPARTURES = Path("theme/departures.yaml")


class Departure(BaseModel):
    id: str
    path: str
    format: Format | None
    source_value: Any
    value: Any
    source: ValueProvenance
    reason: str
    approved_by: str
    approved_at: str
    status: Literal["active", "withdrawn"] = "active"


class DepartureNotApproved(Exception):
    def __init__(self, proposal: Departure) -> None:
        self.proposal = proposal
        super().__init__(f"Departure requires approval: {proposal.path}")


def load_departures(brand: Path) -> list[Departure]:
    path = brand / DEPARTURES
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Departure.model_validate(item) for item in data["departures"]]


def _get(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        current = current[part]
    return current


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str) and left.startswith("#") and right.startswith("#"):
        return left.lower() == right.lower()
    try:
        return abs(to_pt(left) - to_pt(right)) < 1e-9
    except (ValueError, TypeError):
        return bool(left == right)


def _format(path: str) -> Format | None:
    parts = path.split(".")
    if parts[0] == "pages" and len(parts) > 1 and parts[1] in ("slides", "doc"):
        return parts[1]  # type: ignore[return-value]
    if parts[:2] == ["type", "scale"] and len(parts) > 2 and parts[2] in ("slides", "doc"):
        return parts[2]  # type: ignore[return-value]
    return None


def _proposal(brand: Path, path: str, value: Any, reason: str) -> Departure | None:
    theme = load_theme(brand / "theme")
    data = yaml.safe_load((brand / "theme/tokens.yaml").read_text(encoding="utf-8"))
    if not theme.info.labelled or path not in token_paths(data):
        raise BrandError(f"Not a labelled token: {path}")
    source = token_label(theme, path)
    old = _get(data, path)
    if source.label not in ("measured", "derived") or _equal(old, value):
        return None
    return Departure(
        id=f"dep-{len(load_departures(brand)) + 1:03d}",
        path=path,
        format=_format(path),
        source_value=old,
        value=value,
        source=source,
        reason=reason,
        approved_by="",
        approved_at=datetime.now(UTC).isoformat(),
    )


def set_token(
    brand: Path,
    path: str,
    value: Any,
    *,
    provenance: ValueProvenance,
    reason: str,
    person: str = "owner",
    approved: bool = False,
) -> Departure | None:
    departure = _proposal(brand, path, value, reason)
    if departure and not approved:
        raise DepartureNotApproved(departure)
    if departure and not reason.strip():
        raise BrandError(f"A reason is required for departure: {path}")
    if departure:
        departure.approved_by = person
    tokens_path = brand / "theme/tokens.yaml"
    provenance_path = brand / "theme/provenance.yaml"
    departures_path = brand / DEPARTURES
    paths = [tokens_path, provenance_path, departures_path]
    original = {p: p.read_bytes() if p.exists() else None for p in paths}
    tokens = yaml.safe_load(original[tokens_path])
    parent = tokens
    parts = path.split(".")
    for part in parts[:-1]:
        parent = parent[part]
    parent[parts[-1]] = value
    labels = yaml.safe_load(original[provenance_path])
    labels["tokens"][path] = provenance.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True)
    try:
        tokens_path.write_text(yaml.safe_dump(tokens, sort_keys=False), encoding="utf-8")
        provenance_path.write_text(yaml.safe_dump(labels, sort_keys=False), encoding="utf-8")
        if departure:
            entries = load_departures(brand) + [departure]
            data = {"departures": [d.model_dump(mode="json", by_alias=True, exclude_none=True) for d in entries]}
            departures_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        load_theme(brand / "theme")
    except ThemeError:
        for file, content in original.items():
            if content is None:
                file.unlink(missing_ok=True)
            else:
                file.write_bytes(content)
        raise
    return departure


def check_departures(brand: Path) -> list[str]:
    data = yaml.safe_load((brand / "theme/tokens.yaml").read_text(encoding="utf-8"))
    paths = token_paths(data)
    return [
        f"Departure {departure.id} is out of sync: {departure.path}"
        for departure in load_departures(brand)
        if departure.status == "active"
        and (departure.path not in paths or not _equal(departure.value, _get(data, departure.path)))
    ]
