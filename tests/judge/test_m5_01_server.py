# Intent: Serve one project locally with host, origin and token protection.

import importlib
import importlib.util
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

try:
    server = importlib.import_module("docla.server.app")
except ImportError as error:
    if error.name not in {"docla.server", "docla.server.app"}:
        raise
    if importlib.util.find_spec("docla.server") is not None:
        if importlib.util.find_spec("docla.server.app") is not None:
            raise
    server = None

ROOT = Path(__file__).resolve().parents[2]


def _server():
    assert server is not None, "docla.server.app must exist"
    assert hasattr(server, "create_app"), "create_app must exist"
    return server


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "memo.md").write_text("---\ntitle: Memo\n---\n", encoding="utf-8")
    (folder / "deck.md").write_text("---\ntitle: Deck\n---\n", encoding="utf-8")
    (folder / "README.md").write_text("# Read me\n", encoding="utf-8")
    (folder / "sub").mkdir()
    (folder / "sub" / "other.md").write_text("---\ntitle: Other\n---\n", encoding="utf-8")
    return folder


def _client(project):
    app_module = _server()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = app_module.create_app(project, "t0ken")
    assert isinstance(app, FastAPI)
    return TestClient(app, base_url="http://127.0.0.1:8765")


def _check(response, status):
    assert response.status_code == status
    assert "access-control-allow-origin" not in response.headers
    if status == 403:
        assert isinstance(response.json()["detail"], str)


def test_D1_projects_are_sorted_working_files(project):
    client = _client(project)
    response = client.get("/api/projects", headers={"X-Docla-Token": "t0ken", "Host": "127.0.0.1:8765"})
    _check(response, 200)
    assert response.json() == {"projects": [{"name": "project", "docs": ["deck", "memo"]}]}


def test_D2_host_is_checked_before_token(project):
    client = _client(project)
    for host in ("evil.example", "127.0.0.1.evil.example:8765", "0.0.0.0:8765"):
        _check(client.get("/api/projects", headers={"Host": host, "X-Docla-Token": "t0ken"}), 403)
    _check(client.get("/api/projects", headers={"Host": "evil.example"}), 403)
    _check(client.get("/api/projects", headers={"Host": "localhost:8765", "X-Docla-Token": "t0ken"}), 200)


def test_D3_origin_must_match_host(project):
    client = _client(project)
    headers = {"Host": "127.0.0.1:8765", "X-Docla-Token": "t0ken"}
    for origin in ("http://localhost:3000", "http://127.0.0.1:9999", "https://127.0.0.1:8765", "null"):
        _check(client.get("/api/projects", headers={**headers, "Origin": origin}), 403)
    _check(client.get("/api/projects", headers={**headers, "Origin": "http://127.0.0.1:8765"}), 200)
    _check(client.get("/api/projects", headers=headers), 200)


def test_D4_token_and_generated_pages(project):
    client = _client(project)
    _check(client.get("/api/projects"), 401)
    _check(client.get("/api/projects", headers={"X-Docla-Token": "wrong"}), 401)
    _check(client.get("/docs"), 404)
    _check(client.get("/openapi.json"), 404)


def test_D5_cli_launches_loopback_with_unique_fragment_tokens(project, monkeypatch, capsys):
    app_module = _server()
    assert hasattr(app_module, "uvicorn"), "server module must expose uvicorn"
    from docla.cli import main
    from fastapi.testclient import TestClient

    calls = []
    monkeypatch.setattr(app_module.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    tokens = []
    for _ in range(2):
        assert main(["serve", str(project), "--port", "8766"]) == 0
        output = capsys.readouterr()
        match = re.fullmatch(r"docla serve: http://127\.0\.0\.1:8766/#token=([A-Za-z0-9_-]{32,})\n", output.out)
        assert match is not None
        tokens.append(match.group(1))
    assert tokens[0] != tokens[1]
    assert len(calls) == 2
    for (app, kwargs), token in zip(calls, tokens):
        assert kwargs == {"host": "127.0.0.1", "port": 8766}
        client = TestClient(app, base_url="http://127.0.0.1:8766")
        _check(client.get("/api/projects", headers={"X-Docla-Token": token}), 200)
        _check(client.get("/api/projects", headers={"X-Docla-Token": "wrong"}), 401)
    assert main(["serve", str(project / "missing")]) == 2
    assert capsys.readouterr().err
    assert len(calls) == 2


def test_D6_dependencies_and_licence_report():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def names(requirements):
        return {re.split(r"[\[<>=!~; ]", requirement, maxsplit=1)[0].lower() for requirement in requirements}

    assert {"fastapi", "uvicorn"} <= names(data["project"]["dependencies"])
    assert "httpx" in names(data["dependency-groups"]["dev"])
    result = subprocess.run([sys.executable, str(ROOT / "scripts/licence_report.py")], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    licences = {parts[0].lower(): " ".join(parts[2:]) for line in result.stdout.splitlines() if len(parts := line.split()) >= 3}
    assert licences["fastapi"] == "MIT"
    assert licences["uvicorn"] == "BSD-3-Clause"
    assert licences["httpx"] == "BSD-3-Clause"
