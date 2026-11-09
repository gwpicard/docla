"""Deterministic readiness checks for stored versions."""

from pydantic import TypeAdapter

from docla.model import Finding
from docla.store import Version, update_manifest


def ship_gate(version: Version) -> list[str]:
    manifest = version.manifest
    reasons: list[str] = []
    if manifest.look is None:
        reasons.append("not fully looked at")
    elif manifest.look.could_not:
        reasons.append(f"not fully looked at: {'; '.join(manifest.look.could_not)}")
    if manifest.findings.error:
        reasons.append(f"{manifest.findings.error} error findings")
    if manifest.final and manifest.gaps:
        reasons.append(f"{len(manifest.gaps)} gaps")
    findings = TypeAdapter(list[Finding]).validate_json((version.path / "findings.json").read_bytes())
    if any(f.tier == "semantic" and f.severity == "error" and f.corroborated is not True for f in findings):
        reasons.append("unacknowledged vision findings")
    return reasons


def mark_ready(version: Version, *, force: bool = False, reason: str | None = None) -> list[str]:
    if force and (reason is None or not reason.strip()):
        raise ValueError("--force requires a non-blank --reason")
    reasons = ship_gate(version)
    if force:
        update_manifest(version.path, state="ready", forced_reason=reason)
    elif not reasons:
        update_manifest(version.path, state="ready")
    return reasons
