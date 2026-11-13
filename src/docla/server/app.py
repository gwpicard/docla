"""Application and entry point for the local visualiser."""

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from docla.server.docs import DocumentService, UnknownDocument, document_names, patch_rejected, unknown_document
from docla.server.docs import router as docs_router
from docla.server.events import EventBus
from docla.server.events import router as events_router
from docla.server.jobs import JobRunner
from docla.server.jobs import router as jobs_router
from docla.server.security import SecurityMiddleware
from docla.server.themes import brands_root
from docla.server.versions import router as versions_router
from docla.server.watch import FileWatcher
from docla.source.patches import PatchRejected
from docla.theme import neutral_theme
from docla.write import Agents

TOKEN_HEADER = "X-Docla-Token"


def create_app(
    project: Path, token: str, *, agents: Agents | None = None, brands: Path | None = None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(app.state.watcher.run())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.project = project.resolve()
    app.state.token = token
    app.state.bus = EventBus()
    app.state.jobs = JobRunner(app.state.bus)
    app.state.theme = neutral_theme()
    app.state.brands = (brands or brands_root(project)).resolve()
    app.state.agents_by_theme = {}
    app.state.agents = agents
    app.state.docs = DocumentService(app.state.project, app.state.bus)
    app.state.watcher = FileWatcher(app.state.docs)
    app.state.preview_locks = {}
    app.state.keepalive = 15.0
    app.add_middleware(SecurityMiddleware, token=token)
    app.include_router(events_router)
    app.include_router(docs_router)
    app.include_router(jobs_router)
    app.include_router(versions_router)
    app.add_exception_handler(UnknownDocument, unknown_document)
    app.add_exception_handler(PatchRejected, patch_rejected)

    @app.get("/api/projects")
    def projects() -> dict[str, list[dict[str, str | list[str]]]]:
        folder: Path = app.state.project
        docs = document_names(folder)
        return {"projects": [{"name": folder.name, "docs": docs}]}

    return app


def serve(project: Path, port: int = 8765, *, token: str | None = None) -> int:
    if token is None:
        token = secrets.token_urlsafe(32)
    app = create_app(project, token)
    print(f"docla serve: http://127.0.0.1:{port}/#token={token}")
    uvicorn.run(app, host="127.0.0.1", port=port)
    return 0
