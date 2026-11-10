"""Application and entry point for the local visualiser."""

import secrets
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from docla.server.events import EventBus, router as events_router
from docla.server.security import SecurityMiddleware

TOKEN_HEADER = "X-Docla-Token"


def create_app(project: Path, token: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.project = project.resolve()
    app.state.token = token
    app.state.bus = EventBus()
    app.state.keepalive = 15.0
    app.add_middleware(SecurityMiddleware, token=token)
    app.include_router(events_router)

    @app.get("/api/projects")
    def projects() -> dict[str, list[dict[str, str | list[str]]]]:
        folder: Path = app.state.project
        docs = sorted(
            path.stem
            for path in folder.glob("*.md")
            if path.is_file() and path.read_text(encoding="utf-8").splitlines()[:1] == ["---"]
        )
        return {"projects": [{"name": folder.name, "docs": docs}]}

    return app


def serve(project: Path, port: int = 8765, *, token: str | None = None) -> int:
    if token is None:
        token = secrets.token_urlsafe(32)
    app = create_app(project, token)
    print(f"docla serve: http://127.0.0.1:{port}/#token={token}")
    uvicorn.run(app, host="127.0.0.1", port=port)
    return 0
