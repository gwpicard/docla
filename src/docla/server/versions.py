"""Read stored versions and request readiness for the visualiser."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import TypeAdapter

from docla.checks.catalogue import all_rules
from docla.model import Finding, Rule
from docla.store import load_version
from docla.store.gate import mark_ready
from docla.theme.rules import load_theme_rules

router = APIRouter()


def finding_views(findings: list[Finding], rules: list[Rule]) -> list[dict[str, Any]]:
    by_id = {rule.id: rule for rule in rules}
    result = []
    for finding in findings:
        rule = by_id.get(finding.rule_id)
        result.append(
            {
                **finding.model_dump(mode="json", by_alias=True),
                "title": rule.title if rule else None,
                "provenance": rule.provenance.model_dump(mode="json") if rule else None,
            }
        )
    return result


def _root(request: Request, doc: str) -> Path:
    source: Path = request.app.state.docs.path(doc)
    return source.parent / f"{source.stem}.versions"


def _version(request: Request, doc: str, n: int) -> Path:
    path = _root(request, doc) / f"v{n}"
    if not path.is_dir():
        raise HTTPException(status_code=404)
    return path


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except (FileNotFoundError, IsADirectoryError):
        raise HTTPException(status_code=404) from None


def _manifest(path: Path) -> dict[str, Any]:
    _read(path / "manifest.json")
    return load_version(path).manifest.model_dump(mode="json")


def _image(path: Path, request: Request) -> Response:
    data = _read(path)
    etag = f'"{hashlib.sha256(data).hexdigest()}"'
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(data, media_type="image/png", headers={"ETag": etag})


@router.get("/api/docs/{doc}/versions")
def versions(doc: str, request: Request) -> dict[str, Any]:
    project: Path = request.app.state.project
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", doc) or not (project / f"{doc}.md").is_file():
        raise HTTPException(status_code=404)
    root = project / f"{doc}.versions"
    if not root.is_dir():
        return {"versions": []}
    paths = [
        (int(match.group(1)), path)
        for path in root.iterdir()
        if path.is_dir() and (match := re.fullmatch(r"v(\d+)", path.name)) and (path / "manifest.json").is_file()
    ]
    return {"versions": [_manifest(path) for _, path in sorted(paths)]}


@router.get("/api/docs/{doc}/versions/{n}/pages")
def pages(doc: str, n: int, request: Request) -> Any:
    return json.loads(_read(_version(request, doc, n) / "pages" / "pages.json"))


@router.get("/api/docs/{doc}/versions/{n}/findings")
def findings(doc: str, n: int, request: Request) -> dict[str, Any]:
    stored = TypeAdapter(list[Finding]).validate_json(_read(_version(request, doc, n) / "findings.json"))
    rules = all_rules() + load_theme_rules(request.app.state.theme)
    return {"findings": finding_views(stored, rules)}


@router.get("/api/docs/{doc}/versions/{n}/page/{k}.png")
def page_image(doc: str, n: int, k: int, request: Request) -> Response:
    return _image(_version(request, doc, n) / "pages" / f"p{k:02d}.png", request)


@router.get("/api/docs/{doc}/versions/{n}/heal")
def heal(doc: str, n: int, request: Request) -> Response:
    return Response(_read(_version(request, doc, n) / "heal.jsonl"), media_type="application/x-ndjson")


@router.get("/api/docs/{doc}/versions/{n}/heal/{name}.png")
def heal_image(doc: str, n: int, name: str, request: Request) -> Response:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise HTTPException(status_code=404)
    return _image(_version(request, doc, n) / "heal" / f"{name}.png", request)


@router.post("/api/docs/{doc}/versions/{n}/ready")
def ready(doc: str, n: int, request: Request) -> dict[str, Any]:
    path = _version(request, doc, n)
    _read(path / "manifest.json")
    _read(path / "findings.json")
    reasons = mark_ready(load_version(path))
    return {"ready": not reasons, "reasons": reasons}
