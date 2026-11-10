from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from docla.model import Document, Patch, PatchOp, Section

TEXT_FIELDS = ("title", "items", "paragraphs", "code", "note", "spoken", "source_line", "data")
IDENTITY_FIELDS = ("id", "intent", "section")
APPEARANCE_KEYS = ("color", "font", "size", "x", "y")


class PatchRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


FactGuard = Callable[[Document, Section], bool]


def apply_patch(doc: Document, patch: Patch, fact_guard: FactGuard | None = None) -> Document:
    """Return a copy of `doc` with every op applied and `rev` increased by one, or raise PatchRejected."""
    if patch.base_rev != doc.rev:
        raise PatchRejected("stale-base-rev", f"patch is based on rev {patch.base_rev}, document is at rev {doc.rev}")
    sections = [s.model_copy(deep=True) for s in doc.sections]
    for op in patch.ops:
        sections = _apply_op(doc, sections, op, fact_guard, patch.author)
    return doc.model_copy(update={"sections": sections, "rev": doc.rev + 1}, deep=True)


def _index(sections: list[Section], section_id: str | None) -> int:
    for i, section in enumerate(sections):
        if section.id == section_id:
            return i
    raise PatchRejected("unknown-section", f"no section with id {section_id!r}")


def _apply_op(
    doc: Document, sections: list[Section], op: PatchOp, fact_guard: FactGuard | None, author: str
) -> list[Section]:
    if op.op == "insert_after":
        return _insert_after(doc, sections, op, fact_guard)
    index = _index(sections, op.section_id)
    old = sections[index]
    if op.op == "delete_section":
        _check_structural_lock(old)
        return sections[:index] + sections[index + 1 :]
    if op.op == "move_section":
        return _move(sections, index, op)
    new = _edited_section(old, op)
    _check_ownership(old, new, author)
    _check_identity(old, new)
    _check_fact(doc, sections, index, new, fact_guard)
    _check_appearance(op)
    new = _validated(new, old)
    return sections[:index] + [new] + sections[index + 1 :]


def _field_updates(op: PatchOp) -> dict[str, Any]:
    fields = op.fields or {}
    if op.op == "set_attr":
        return {str(fields.get("name")): fields.get("value")}
    return dict(fields)


def _edited_section(old: Section, op: PatchOp) -> dict[str, Any] | Section:
    """Return the proposed section data; it is validated only after the guards ran."""
    if op.op == "replace_section":
        if op.value is None:
            raise PatchRejected("invalid-section", "replace_section needs a value")
        return op.value
    return {**old.model_dump(), **_field_updates(op)}


def _as_dict(section: dict[str, Any] | Section) -> dict[str, Any]:
    return section if isinstance(section, dict) else section.model_dump()


def _changed(old: Section, new: dict[str, Any] | Section, names: tuple[str, ...]) -> list[str]:
    old_data, new_data = old.model_dump(), _as_dict(new)
    return [n for n in names if n in new_data and new_data[n] != old_data[n]]


def _check_ownership(old: Section, new: dict[str, Any] | Section, author: str) -> None:
    if old.lock == "all" and _changed(old, new, ("intent", "component")):
        raise PatchRejected("lock-all", f"section {old.id} is locked")
    if author != "human" and (old.owner == "human" or old.lock in ("text", "all")) and _changed(old, new, TEXT_FIELDS):
        raise PatchRejected("owner-locked", f"text of section {old.id} is owned by a human or locked")


def _check_structural_lock(old: Section) -> None:
    if old.lock == "all":
        raise PatchRejected("lock-all", f"section {old.id} is locked")


def _check_identity(old: Section, new: dict[str, Any] | Section) -> None:
    if _changed(old, new, IDENTITY_FIELDS):
        raise PatchRejected("identity-changed", f"id, intent and section of {old.id} cannot change")


def _check_appearance(op: PatchOp) -> None:
    forbidden = [k for k in _field_updates(op) if k in APPEARANCE_KEYS]
    if forbidden:
        raise PatchRejected("appearance-forbidden", f"appearance is not patchable: {', '.join(forbidden)}")


def _validated(new: dict[str, Any] | Section, old: Section | None) -> Section:
    data = _as_dict(new)
    unknown = [k for k in data if k not in Section.model_fields]
    if unknown:
        raise PatchRejected("invalid-section", f"unknown section fields: {', '.join(unknown)}")
    try:
        section = Section.model_validate(data)
    except ValidationError as error:
        raise PatchRejected("invalid-section", str(error)) from error
    if section.component and not section.because and (old is None or old.component != section.component):
        raise PatchRejected("invalid-section", "a component needs a because")
    return section


def _check_fact(
    doc: Document, sections: list[Section], index: int, new: dict[str, Any] | Section, fact_guard: FactGuard | None
) -> None:
    if fact_guard is None:
        return
    try:
        candidate = Section.model_validate(_as_dict(new))
    except ValidationError:
        return  # the section validation reports it
    working = doc.model_copy(update={"sections": sections[:index] + [candidate] + sections[index + 1 :]})
    if not fact_guard(working, candidate):
        raise PatchRejected("fact-unsupported", f"section {candidate.id} has claims the sources do not support")


def _insert_after(doc: Document, sections: list[Section], op: PatchOp, fact_guard: FactGuard | None) -> list[Section]:
    index = _index(sections, op.after_id) if op.after_id is not None else -1
    if op.value is None:
        raise PatchRejected("invalid-section", "insert_after needs a value")
    if op.value.id is not None and any(s.id == op.value.id for s in sections):
        raise PatchRejected("identity-changed", f"section id {op.value.id!r} already exists")
    if fact_guard is not None:
        working = doc.model_copy(update={"sections": sections[: index + 1] + [op.value] + sections[index + 1 :]})
        if not fact_guard(working, op.value):
            raise PatchRejected("fact-unsupported", f"section {op.value.id} has claims the sources do not support")
    new = _validated(op.value, None)
    return sections[: index + 1] + [new] + sections[index + 1 :]


def _move(sections: list[Section], index: int, op: PatchOp) -> list[Section]:
    _check_structural_lock(sections[index])
    target = _index(sections, op.after_id)
    if target == index:
        return sections
    moved = sections[index]
    rest = sections[:index] + sections[index + 1 :]
    position = _index(rest, op.after_id)
    return rest[: position + 1] + [moved] + rest[position + 1 :]


def inverse_ops(before: Document, patch: Patch) -> list[PatchOp] | None:
    """Build inverse operations in reverse order against each intermediate state."""
    sections = [s.model_copy(deep=True) for s in before.sections]
    inverse: list[PatchOp] = []
    for op in patch.ops:
        if op.op == "set_fields":
            old = sections[_index(sections, op.section_id)]
            undo = [
                PatchOp(
                    op="set_fields",
                    section_id=op.section_id,
                    fields={key: old.model_dump()[key] for key in (op.fields or {})},
                )
            ]
        elif op.op == "insert_after" and op.value is not None and op.value.id is not None:
            undo = [PatchOp(op="delete_section", section_id=op.value.id)]
        elif op.op == "delete_section":
            index = _index(sections, op.section_id)
            old = sections[index]
            if len(sections) == 1:
                undo = [PatchOp(op="insert_after", section_id=op.section_id, after_id=None, value=old)]
            else:
                neighbour = sections[index - 1] if index else sections[1]
                undo = [PatchOp(op="insert_after", section_id=op.section_id, after_id=neighbour.id, value=old)]
                if index == 0:
                    assert neighbour.id is not None
                    undo.append(PatchOp(op="move_section", section_id=neighbour.id, after_id=old.id))
        else:
            return None
        inverse = undo + inverse
        sections = _apply_op(before, sections, op, None, patch.author)
    return inverse


def diff_ops(before: Document, after: Document) -> list[PatchOp]:
    """Describe section changes and ordering in terms of patch operations."""
    old = {s.id: s for s in before.sections if s.id is not None}
    ops: list[PatchOp] = []
    for section in after.sections:
        if section.id in old and section.id is not None:
            prior = old[section.id].model_dump()
            fields = {k: v for k, v in section.model_dump().items() if v != prior[k]}
            if fields:
                ops.append(PatchOp(op="set_fields", section_id=section.id, fields=fields))
    order = [s.id for s in before.sections]
    desired: list[str | None] = []
    for index, section in enumerate(after.sections):
        key = section.id if section.id is not None else f"__new_{index}"
        desired.append(key)
        if section.id is None or section.id not in old:
            anchor = desired[-2] if len(desired) > 1 else order[0]
            ops.append(PatchOp(op="insert_after", section_id=key, after_id=anchor, value=section))
            order.insert(order.index(anchor) + 1, key)
    for section in before.sections:
        if section.id not in desired:
            assert section.id is not None
            ops.append(PatchOp(op="delete_section", section_id=section.id))
            order.remove(section.id)
    for index in range(len(desired)):
        while order[index] != desired[index]:
            if index == 0:
                moving, anchor = order[0], desired[0]
            else:
                moving, anchor = desired[index], desired[index - 1]
            assert moving is not None
            ops.append(PatchOp(op="move_section", section_id=moving, after_id=anchor))
            order.remove(moving)
            order.insert(order.index(anchor) + 1, moving)
    return ops
