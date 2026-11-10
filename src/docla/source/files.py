import json
import os
import tempfile
from pathlib import Path

from docla.model import Document, Patch
from docla.source.ids import IdStore, stamp
from docla.source.parser import parse
from docla.source.patches import FactGuard, PatchRejected, apply_patch, inverse_ops
from docla.source.serialiser import serialise

UNPARSEABLE_RULES = ("source.parse-error", "source.appearance-in-source")


def current_rev(oplog: Path) -> int:
    """The revision is the number of non-empty lines in the log; 0 when there is no log."""
    if not oplog.exists():
        return 0
    return sum(1 for line in oplog.read_text(encoding="utf-8").splitlines() if line.strip())


def _write_atomic(path: Path, text: str) -> None:
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as temp:
            temp.write(text)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _append_log(oplog: Path, path: Path, patch: Patch, rev: int, before: Document) -> None:
    inverse = inverse_ops(before, patch)
    entry = {
        "rev": rev,
        "author": patch.author,
        "reason": patch.reason,
        "finding_ids": patch.finding_ids,
        "ops": [op.model_dump(mode="json") for op in patch.ops],
        "file": path.name,
        "inverse": [op.model_dump(mode="json") for op in inverse] if inverse is not None else None,
    }
    oplog.parent.mkdir(parents=True, exist_ok=True)
    with oplog.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _parse_editable(path: Path) -> Document:
    doc, findings = parse(path.read_bytes().decode("utf-8"))
    broken = sorted({f.rule_id for f in findings if f.rule_id in UNPARSEABLE_RULES})
    if broken:
        raise PatchRejected("unparseable", f"{path.name} cannot be edited safely: {', '.join(broken)}")
    return doc


def apply_to_file(path: Path, patch: Patch, oplog: Path, ids: IdStore, fact_guard: FactGuard | None = None) -> Document:
    """Apply `patch` to the working file at `path` and append the change to `oplog`."""
    doc = _parse_editable(path)
    stamped, _ = stamp(doc, ids)
    stamped = stamped.model_copy(update={"rev": current_rev(oplog)})
    result = apply_patch(stamped, patch, fact_guard)
    ids.save()
    _write_atomic(path, serialise(result))
    _append_log(oplog, path, patch, result.rev, stamped)
    return result


def apply_to_document(path: Path, before: Document, patch: Patch, oplog: Path, ids: IdStore) -> Document:
    """Apply a patch to the last good document and persist it."""
    patch = patch.model_copy(deep=True)
    replacements: dict[str, str] = {}
    existing = {s.id for s in before.sections if s.id is not None}
    for op in patch.ops:
        if op.after_id in replacements:
            op.after_id = replacements[op.after_id]
        if op.section_id in replacements:
            op.section_id = replacements[op.section_id]
        if op.op == "insert_after" and op.value is not None and op.value.id is None:
            new_id = ids.allocate(existing=existing)
            existing.add(new_id)
            replacements[op.section_id] = new_id
            op.section_id = new_id
            op.value.id = new_id
    base = before.model_copy(update={"rev": current_rev(oplog)})
    result = apply_patch(base, patch)
    ids.save()
    _write_atomic(path, serialise(result))
    _append_log(oplog, path, patch, result.rev, base)
    return result
