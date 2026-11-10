"""Document access and human edits for the visualiser."""

import asyncio
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from docla.model import Document, Patch, PatchOp, Section
from docla.render.compose import component_for
from docla.server.events import EventBus
from docla.server.preview import preview
from docla.source import parse
from docla.source.files import UNPARSEABLE_RULES, apply_to_file, current_rev
from docla.source.ids import IdStore
from docla.source.patches import TEXT_FIELDS, PatchRejected


class UnknownDocument(Exception):
    pass


def document_names(project: Path) -> list[str]:
    return sorted(
        path.stem
        for path in project.glob("*.md")
        if path.is_file() and path.read_text(encoding="utf-8").splitlines()[:1] == ["---"]
    )


class DocumentService:
    def __init__(self, project: Path, bus: EventBus) -> None:
        self.project = project
        self.bus = bus
        self.oplog = project / ".docla" / "oplog.jsonl"
        self.ids = IdStore(project / ".docla" / "ids.json")
        self.lock = asyncio.Lock()
        self.last_good: dict[str, Document] = {}
        self.last_bytes: dict[str, bytes] = {}
        self.last_rev: dict[str, int] = {}

    def path(self, name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name) or name not in document_names(self.project):
            raise UnknownDocument(name)
        return self.project / f"{name}.md"

    def load(self, name: str) -> Document:
        data = self.path(name).read_bytes()
        doc, findings = parse(data.decode("utf-8"))
        if any(f.rule_id in UNPARSEABLE_RULES for f in findings) and name in self.last_good:
            return self.last_good[name]
        doc = doc.model_copy(update={"rev": current_rev(self.oplog)})
        self.record(name, data, doc)
        return doc

    def record(self, name: str, data: bytes, doc: Document) -> None:
        self.last_good[name] = doc
        self.last_bytes[name] = data
        self.last_rev[name] = current_rev(self.oplog)

    def _apply(self, name: str, patch: Patch) -> Document:
        result = apply_to_file(self.path(name), patch, self.oplog, self.ids)
        self.record(name, self.path(name).read_bytes(), result)
        self.bus.publish("doc.changed", {"doc": name, "rev": result.rev, "by": "human"})
        return result

    async def edit(self, name: str, section_id: str, base_rev: int, fields: dict[str, Any]) -> int:
        async with self.lock:
            self.path(name)
            if any(key not in TEXT_FIELDS for key in fields):
                raise PatchRejected("invalid-fields", "Only text fields can be edited")
            op = PatchOp(op="set_fields", section_id=section_id, fields={**fields, "owner": "human"})
            return self._apply(name, Patch(author="human", reason="edit", base_rev=base_rev, ops=[op])).rev

    async def add(self, name: str, after_id: str, intent: str, section: str | None) -> tuple[int, str]:
        async with self.lock:
            doc = self.load(name)
            new_id = self.ids.allocate(existing=(s.id for s in doc.sections if s.id is not None))
            op = PatchOp(
                op="insert_after",
                section_id=new_id,
                after_id=after_id,
                value=Section(id=new_id, intent=intent, section=section),
            )
            result = self._apply(name, Patch(author="human", reason="add", base_rev=doc.rev, ops=[op]))
            return result.rev, new_id

    async def delete(self, name: str, section_id: str) -> int:
        async with self.lock:
            doc = self.load(name)
            op = PatchOp(op="delete_section", section_id=section_id)
            return self._apply(name, Patch(author="human", reason="delete", base_rev=doc.rev, ops=[op])).rev


class EditBody(BaseModel):
    base_rev: int
    fields: dict[str, Any]


class AddBody(BaseModel):
    after_id: str
    intent: str
    section: str | None = None


router = APIRouter()


@router.get("/api/docs/{doc}")
def get_document(doc: str, request: Request) -> dict[str, Any]:
    document = request.app.state.docs.load(doc)
    outline = [
        {
            "id": s.id,
            "intent": s.intent,
            "section": s.section,
            "title": s.title,
            "component": component_for(s, document.format, index, len(document.sections)),
            "owner": s.owner,
            "lock": s.lock,
        }
        for index, s in enumerate(document.sections)
    ]
    return {
        "document": document.model_dump(mode="json"),
        "sections": document.model_dump(mode="json")["sections"],
        "rev": document.rev,
        "outline": outline,
    }


@router.patch("/api/docs/{doc}/sections/{section_id}")
async def edit_document(doc: str, section_id: str, body: EditBody, request: Request) -> dict[str, int]:
    rev = await request.app.state.docs.edit(doc, section_id, body.base_rev, body.fields)
    document = request.app.state.docs.last_good[doc]
    asyncio.create_task(preview(request.app.state, doc, section_id, rev, document))
    return {"rev": rev}


@router.post("/api/docs/{doc}/sections")
async def add_section(doc: str, body: AddBody, request: Request) -> dict[str, Any]:
    rev, section_id = await request.app.state.docs.add(doc, body.after_id, body.intent, body.section)
    return {"rev": rev, "id": section_id}


@router.delete("/api/docs/{doc}/sections/{section_id}")
async def delete_section(doc: str, section_id: str, request: Request) -> dict[str, int]:
    return {"rev": await request.app.state.docs.delete(doc, section_id)}


async def unknown_document(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Unknown document"})


async def patch_rejected(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PatchRejected)
    if exc.code == "stale-base-rev":
        doc = request.app.state.docs.load(request.path_params["doc"])
        return JSONResponse(
            status_code=409, content={"detail": str(exc), "rev": doc.rev, "document": doc.model_dump(mode="json")}
        )
    if exc.code == "unknown-section":
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    return JSONResponse(status_code=422, content={"code": exc.code, "message": exc.message})
