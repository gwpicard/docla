# Intent: Preserve versions, reversible edits, and revision-accurate previews during concurrent work.
import importlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docla.model import Patch, PatchOp
from docla.source import parse, serialise
from docla.source.files import apply_to_file, current_rev
from docla.source.ids import IdStore
from docla.write import Agents
from judge.test_m1_17_cli_build_check import SLIDES as BUILD_SLIDES
from judge.test_m4_07_versions import _write
from judge.test_m5_03_document_api import SLIDES
from judge.test_m5_04_jobs import FakeWriter


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name
        if not missing or not (name == missing or name.startswith(missing + ".")):
            raise
        if importlib.util.find_spec(missing) is not None:
            raise
        return None


store = _module("docla.store")
server = _module("docla.server.app")
patches = _module("docla.source.patches")
preview = _module("docla.server.preview")
pytest_plugins = ["judge.test_m4_07_versions"]
ROOT = Path(__file__).resolve().parents[2]


def _client(app):
    return TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Docla-Token": "test-token"})


def test_D1_atomic_claim_preserves_other_build(deck, monkeypatch):
    assert store is not None and hasattr(store, "write_version") and hasattr(store, "VersionImmutable")
    root = deck[0].parent / "deck.versions"
    original = os.mkdir

    def competing(path, *args, **kwargs):
        path = Path(path)
        if path.parent == root and re.fullmatch(r"v\d+", path.name):
            original(path, *args, **kwargs)
        return original(path, *args, **kwargs)

    with monkeypatch.context() as context:
        context.setattr(os, "mkdir", competing)
        with pytest.raises(store.VersionImmutable):
            _write(deck)
    assert [p.name for p in root.iterdir()] == ["v1"]
    assert list((root / "v1").iterdir()) == []


def test_D1_sequential_versions(deck):
    assert store is not None and hasattr(store, "write_version")
    assert [_write(deck).number, _write(deck).number] == [1, 2]


def test_D2_incomplete_version_is_excluded(deck):
    assert server is not None and hasattr(server, "create_app")
    assert store is not None and hasattr(store, "write_version")
    version = _write(deck)
    (version.path.parent / "v2").mkdir()
    app = server.create_app(deck[0].parent, "test-token")
    with _client(app) as client:
        response = client.get("/api/docs/deck/versions")
    assert response.status_code == 200
    assert response.json() == {"versions": [version.manifest.model_dump(mode="json")]}


def test_D3_only_section_inverse_round_trip():
    assert patches is not None and hasattr(patches, "inverse_ops") and hasattr(patches, "apply_patch")
    doc = parse(SLIDES)[0].model_copy(update={"sections": [parse(SLIDES)[0].sections[0]]})
    deletion = Patch(
        base_rev=0, author="human", reason="delete", ops=[PatchOp(op="delete_section", section_id="aaaa1")]
    )
    inverse = patches.inverse_ops(doc, deletion)
    assert inverse == [PatchOp(op="insert_after", section_id="aaaa1", after_id=None, value=doc.sections[0])]
    empty = patches.apply_patch(doc, deletion)
    restored = patches.apply_patch(empty, Patch(base_rev=1, author="human", reason="undo", ops=inverse))
    assert restored.sections == doc.sections


def test_D3_server_deletions_record_reversible_inverses(tmp_path):
    assert server is not None and hasattr(server, "create_app")
    path = tmp_path / "deck.md"
    path.write_text(serialise(parse(SLIDES)[0]), encoding="utf-8")
    original = path.read_bytes()
    app = server.create_app(tmp_path, "test-token")
    with _client(app) as client:
        first = client.delete("/api/docs/deck/sections/aaaa2")
        assert first.status_code == 200 and first.json() == {"rev": 1}
        after_first = path.read_bytes()
        second = client.delete("/api/docs/deck/sections/aaaa1")
        assert second.status_code == 200 and second.json() == {"rev": 2}
    log = tmp_path / ".docla/oplog.jsonl"
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(entries) == 2
    assert all(isinstance(entry["inverse"], list) and entry["inverse"] for entry in entries)
    for entry, expected in zip(reversed(entries), (after_first, original), strict=True):
        patch = Patch(
            base_rev=current_rev(log),
            author="human",
            reason="undo",
            ops=[PatchOp.model_validate(op) for op in entry["inverse"]],
        )
        apply_to_file(path, patch, log, IdStore(log.parent / "ids.json"))
        assert path.read_bytes() == expected


def test_D4_preview_matches_accepted_revision(tmp_path, monkeypatch):
    assert server is not None and hasattr(server, "create_app")
    assert preview is not None and hasattr(preview, "_render")
    shutil.copyfile(ROOT / "tests/fixtures/seeded-defects/geo.text-fits/pass/doc.md", tmp_path / "deck.md")
    started, release = threading.Event(), threading.Event()
    calls = []

    def render(state, doc, section_id):
        calls.append(section_id)
        if len(calls) == 1:
            started.set()
            assert release.wait(10)
        title = next(s.title for s in doc.sections if s.id == section_id)
        return {"state": "clean", "findings": [], "png": "iVBORw0KGgo=", "title": title}

    monkeypatch.setattr(preview, "_render", render)
    app = server.create_app(tmp_path, "test-token")
    with _client(app) as client:
        try:
            for rev, title in enumerate(("Zero", "First", "Second")):
                response = client.patch(
                    "/api/docs/deck/sections/c4e10", json={"base_rev": rev, "fields": {"title": title}}
                )
                assert response.status_code == 200 and response.json() == {"rev": rev + 1}
                if rev == 0:
                    assert started.wait(10)
        finally:
            release.set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            events = list(app.state.bus.recent())
            finals = [e["data"] for e in events if e["type"] == "section.state" and e["data"].get("state") == "clean"]
            if any(e.get("rev") == 3 for e in finals):
                break
            time.sleep(0.01)
        assert any(e["rev"] == 3 and e["title"] == "Second" for e in finals)
        for rev, title in ((1, "Zero"), (2, "First"), (3, "Second")):
            assert all(e["title"] == title for e in finals if e["rev"] == rev)


def test_D5_critic_human_edit_marks_build_stale(tmp_path):
    assert server is not None and hasattr(server, "create_app")
    path = tmp_path / "deck.md"
    path.write_text(serialise(parse(BUILD_SLIDES)[0]), encoding="utf-8")
    calls = []

    def critic_factory(doc):
        async def critic(page):
            calls.append(page)
            if len(calls) == 1:
                log = tmp_path / ".docla/oplog.jsonl"
                patch = Patch(
                    base_rev=current_rev(log),
                    author="human",
                    reason="edit during look",
                    ops=[PatchOp(op="set_fields", section_id="aaaa1", fields={"title": "One pilot"})],
                )
                apply_to_file(path, patch, log, IdStore(log.parent / "ids.json"))
            return []

        return critic

    agents = Agents(
        gather=lambda *a: None,
        outline=lambda *a: None,
        writer=lambda facts, doc: FakeWriter(doc),
        critic=critic_factory,
    )
    app = server.create_app(tmp_path, "test-token", agents=agents)
    with _client(app) as client:
        response = client.post("/api/docs/deck/build", json={"mode": "draft"})
        assert response.status_code == 202
        job_id = response.json()["job"]
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = app.state.jobs.get(job_id)
            assert job is not None
            if job.status != "running":
                break
            time.sleep(0.05)
        assert job.status == "finished", job.error
        assert job.result == {"version": 1, "stale": True, "snapshot_rev": 0}
        assert calls


def test_D6_frozen_judges_pass():
    names = [
        "test_m1_4a_patches.py",
        "test_m1_4b_files.py",
        "test_m4_07_versions.py",
        "test_m5_03_document_api.py",
        "test_m5_04_jobs.py",
        "test_m5_05_versions_api.py",
        "test_m5_06_fast_preview.py",
        "test_m5_07_file_watcher.py",
    ]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *[str(ROOT / "tests/judge" / name) for name in names]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
