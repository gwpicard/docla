import json
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from docla.source.patches import TEXT_FIELDS


def _fields_for_op(op: dict[str, Any]) -> tuple[str | None, set[str]]:
    kind = op.get("op")
    if kind == "set_fields":
        fields = op.get("fields")
        return op.get("section_id"), set(fields).intersection(TEXT_FIELDS) if isinstance(fields, dict) else set()
    if kind in ("replace_section", "insert_after"):
        value = op.get("value")
        if isinstance(value, dict):
            section_id = value.get("id") if kind == "insert_after" else op.get("section_id")
            return section_id, {field for field in TEXT_FIELDS if value.get(field) not in (None, "", [])}
    return None, set()


def person_fields(oplog: Path, file_name: str) -> dict[str, set[str]]:
    """Collect the text fields written by a person for one working file."""
    kept: dict[str, set[str]] = {}
    if not oplog.exists():
        return kept
    with oplog.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict) or entry.get("file") != file_name or entry.get("author") != "human":
                continue
            ops = entry.get("ops")
            if not isinstance(ops, list):
                continue
            for op in ops:
                if isinstance(op, dict):
                    section_id, fields = _fields_for_op(op)
                    if isinstance(section_id, str) and fields:
                        kept.setdefault(section_id, set()).update(fields)
    return kept


def release(kept: Mapping[str, Collection[str]], section_id: str, field: str) -> dict[str, set[str]]:
    """Return an independent copy with the specified field released."""
    result = {key: set(fields) for key, fields in kept.items()}
    if section_id in result:
        result[section_id].discard(field)
    return result
