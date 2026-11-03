import json
import os
import tempfile
from pathlib import Path

from doclo.model import Document, Patch
from doclo.source.ids import IdStore, stamp
from doclo.source.parser import parse
from doclo.source.patches import FactGuard, PatchRejected, apply_patch
from doclo.source.serialiser import serialise

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


def _append_log(oplog: Path, path: Path, patch: Patch, rev: int) -> None:
    entry = {
        "rev": rev,
        "author": patch.author,
        "reason": patch.reason,
        "finding_ids": patch.finding_ids,
        "ops": [op.model_dump(mode="json") for op in patch.ops],
        "file": path.name,
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
    _append_log(oplog, path, patch, result.rev)
    return result
