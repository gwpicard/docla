from typing import Any, Literal

from pydantic import BaseModel, Field

from docla.model.source import Section


class PatchOp(BaseModel):
    op: Literal["replace_section", "set_fields", "insert_after", "delete_section", "set_attr", "move_section"]
    section_id: str
    fields: dict[str, Any] | None = None
    value: Section | None = None
    after_id: str | None = None


class Patch(BaseModel):
    base_rev: int
    author: Literal["ai", "human", "system"]
    reason: str
    finding_ids: list[str] = Field(default_factory=list)
    ops: list[PatchOp]
