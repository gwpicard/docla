# Intent: External edits become human patches while invalid edits preserve the last good document.
import asyncio
import importlib.util
import json
import re

import pytest

from docla.model import Patch, PatchOp
from docla.source.files import apply_to_file
from docla.source.ids import IdStore
from docla.source.parser import parse


def _optional_module(name):
    try:
        return __import__(name, fromlist=["*"])
    except ImportError as error:
        if error.name == name or (
            error.name and name.startswith(error.name + ".") and importlib.util.find_spec(error.name) is None
        ):
            return None
        raise


app_module = _optional_module("docla.server.app")
watch_module = _optional_module("docla.server.watch")

SLIDES = """---
doctype: pitch-deck
format: slides
title: Readout
---

## Sources

- [S1] workshop.vtt, transcript

::: {#aaaa1 .section intent="statement"}
## One pilot is enough
:::

::: {#aaaa2 .section intent="bullets"}
## Why it works

- Short intervals catch drift early. [S1 00:41]
- Cheap to repeat.
:::
"""


def _setup(tmp_path):
    assert app_module is not None and hasattr(app_module, "create_app"), "create_app must exist"
    assert watch_module is not None and hasattr(watch_module, "FileWatcher"), "FileWatcher must exist"
    from fastapi.testclient import TestClient

    path = tmp_path / "deck.md"
    path.write_text(SLIDES, encoding="utf-8")
    app = app_module.create_app(tmp_path, "secret")
    client = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Docla-Token": "secret"})
    assert hasattr(app.state, "watcher"), "create_app must install a watcher"
    return path, app, client


def _poll(app):
    return asyncio.run(app.state.watcher.poll())


def _log(tmp_path):
    path = tmp_path / ".docla" / "oplog.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _events(app, kind):
    return [event["data"] for event in app.state.bus.recent() if event["type"] == kind]


def _document(client):
    response = client.get("/api/docs/deck")
    assert response.status_code == 200, response.text
    return response.json()


def test_D1_stable_external_edit_becomes_one_human_patch(tmp_path):
    path, app, client = _setup(tmp_path)
    assert _poll(app) == []
    path.write_text(SLIDES.replace("Why it works", "Why it lasts"), encoding="utf-8")
    assert _poll(app) == []
    assert _poll(app) == ["deck"]
    log = _log(tmp_path)
    assert len(log) == 1 and log[0]["author"] == "human"
    assert len(log[0]["ops"]) == 1
    assert log[0]["ops"][0]["op"] == "set_fields"
    assert log[0]["ops"][0]["section_id"] == "aaaa2"
    doc = _document(client)
    assert doc["rev"] == 1
    section = next(s for s in doc["sections"] if s["id"] == "aaaa2")
    assert section["title"] == "Why it lasts" and section["owner"] == "human"
    assert _events(app, "doc.changed") == [{"doc": "deck", "rev": 1, "by": "human"}]
    assert _poll(app) == []
    assert _events(app, "doc.changed") == [{"doc": "deck", "rev": 1, "by": "human"}]


def test_D2_api_and_other_in_process_writes_are_not_external(tmp_path):
    path, app, client = _setup(tmp_path)
    assert _poll(app) == []
    response = client.patch("/api/docs/deck/sections/aaaa2", json={"base_rev": 0, "fields": {"title": "Edited"}})
    assert response.status_code == 200, response.text
    before_log, before_events = _log(tmp_path), _events(app, "doc.changed")
    assert len(before_log) == 1
    assert _poll(app) == []
    assert _log(tmp_path) == before_log and _events(app, "doc.changed") == before_events
    patch = Patch(
        base_rev=1,
        author="ai",
        reason="Improve title",
        ops=[PatchOp(op="set_fields", section_id="aaaa1", fields={"title": "A new pilot"})],
    )
    apply_to_file(path, patch, tmp_path / ".docla" / "oplog.jsonl", IdStore(tmp_path / ".docla" / "ids.json"))
    assert _poll(app) == ["deck"]
    assert len(_log(tmp_path)) == 2
    doc = _document(client)
    section = next(s for s in doc["sections"] if s["id"] == "aaaa1")
    assert section["title"] == "A new pilot" and section["owner"] is None
    assert _events(app, "doc.changed") == before_events + [{"doc": "deck", "rev": 2, "by": "ai"}]


def test_D3_external_insert_and_delete_stamp_id(tmp_path):
    path, app, _ = _setup(tmp_path)
    assert _poll(app) == []
    edited = SLIDES.replace('::: {#aaaa1 .section intent="statement"}\n## One pilot is enough\n:::\n\n', "")
    edited += '\n::: {.section intent="statement"}\n## Another point\n:::\n'
    path.write_text(edited, encoding="utf-8")
    assert _poll(app) == []
    assert _poll(app) == ["deck"]
    log = _log(tmp_path)
    assert len(log) == 1
    assert {op["op"] for op in log[0]["ops"]} >= {"delete_section", "insert_after"}
    doc, findings = parse(path.read_text(encoding="utf-8"))
    assert not [f for f in findings if f.rule_id == "source.parse-error"]
    assert [s.id for s in doc.sections][0] == "aaaa2"
    assert len(doc.sections) == 2 and re.fullmatch(r"[0-9a-f]{5}", doc.sections[1].id)
    assert doc.sections[1].id != "aaaa1" and doc.sections[1].owner == "human"


def test_D4_invalid_edit_is_reported_once_and_recovery_applies(tmp_path):
    path, app, client = _setup(tmp_path)
    assert _poll(app) == []
    original = _document(client)
    broken = SLIDES.replace("title: Readout\n---", "title: Readout", 1).encode()
    path.write_bytes(broken)
    assert _poll(app) == []
    assert _poll(app) == ["deck"]
    assert path.read_bytes() == broken and _log(tmp_path) == []
    events = _events(app, "queue.changed")
    assert len(events) == 1 and events[0]["doc"] == "deck"
    assert any(f["rule_id"] == "source.parse-error" for f in events[0]["findings"])
    assert _document(client) == original
    assert _poll(app) == [] and _events(app, "queue.changed") == events
    path.write_text(SLIDES.replace("Why it works", "Why it lasts"), encoding="utf-8")
    assert _poll(app) == []
    assert _poll(app) == ["deck"]
    assert len(_log(tmp_path)) == 1 and _log(tmp_path)[0]["author"] == "human"
    doc = _document(client)
    assert doc["rev"] == 1
    assert next(s for s in doc["sections"] if s["id"] == "aaaa2")["title"] == "Why it lasts"
    assert _events(app, "doc.changed") == [{"doc": "deck", "rev": 1, "by": "human"}]


def test_D5_run_polls_with_injected_sleep(tmp_path):
    path, app, _ = _setup(tmp_path)
    calls = []

    async def fake_sleep(interval):
        calls.append(interval)
        if len(calls) == 1:
            path.write_text(SLIDES.replace("Why it works", "Why it lasts"), encoding="utf-8")
        if len(calls) == 3:
            raise asyncio.CancelledError

    watcher = watch_module.FileWatcher(app.state.docs, interval=0.25, sleep=fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(watcher.run())
    assert calls == [0.25, 0.25, 0.25]
    assert _events(app, "doc.changed") == [{"doc": "deck", "rev": 1, "by": "human"}]
