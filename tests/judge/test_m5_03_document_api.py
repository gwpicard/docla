# Intent: The server reads and changes documents, records inverses, and announces edits.
import importlib.util
import json
import re

import pytest

from docla.model import Patch, PatchOp
from docla.source import parse, serialise
from docla.source.files import apply_to_file, current_rev
from docla.source.ids import IdStore
from docla.source.patches import PatchRejected, apply_patch

try:
    from docla.server import app as server_app
except ImportError as error:
    if error.name not in ("docla.server", "docla.server.app"):
        raise
    if importlib.util.find_spec("docla.server") is not None and importlib.util.find_spec("docla.server.app") is not None:
        raise
    server_app = None

SLIDES = '''---
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
'''


@pytest.fixture
def session(tmp_path):
    if server_app is None or not hasattr(server_app, "create_app"):
        yield None
        return
    from fastapi.testclient import TestClient

    path = tmp_path / "deck.md"
    path.write_text(serialise(parse(SLIDES)[0]), encoding="utf-8")
    app = server_app.create_app(tmp_path, "test-token")
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Docla-Token": "test-token"}) as client:
        yield client, app, path, tmp_path / ".docla" / "oplog.jsonl"


def _edit(client, rev=0, section="aaaa2", fields=None):
    return client.patch(f"/api/docs/deck/sections/{section}", json={
        "base_rev": rev, "fields": fields if fields is not None else {"title": "Why it still works"},
    })


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_D1_document_outline_and_invalid_names(session):
    assert session is not None, "docla.server.app.create_app must exist"
    client, _, _, _ = session
    response = client.get("/api/docs/deck")
    assert response.status_code == 200
    body = response.json()
    assert body["rev"] == 0
    assert [s["id"] for s in body["document"]["sections"]] == ["aaaa1", "aaaa2"]
    assert [s["id"] for s in body["outline"]] == ["aaaa1", "aaaa2"]
    assert [s["component"] for s in body["outline"]] == ["statement", "bullets"]
    for name in ("nope", "..%2Fdeck", "deck.md"):
        assert client.get(f"/api/docs/{name}").status_code == 404


def test_D2_human_edits_and_ai_remains_locked(session):
    assert session is not None, "docla.server.app.create_app must exist"
    client, _, path, oplog = session
    response = _edit(client)
    assert response.status_code == 200 and response.json() == {"rev": 1}
    doc = parse(path.read_text(encoding="utf-8"))[0]
    assert doc.sections[1].title == "Why it still works" and doc.sections[1].owner == "human"
    entry = _lines(oplog)[-1]
    assert entry["author"] == "human"
    assert len(entry["ops"]) == 1 and entry["ops"][0]["op"] == "set_fields"
    response = _edit(client, 1, fields={"title": "A second edit"})
    assert response.status_code == 200 and response.json() == {"rev": 2}
    doc = parse(path.read_text(encoding="utf-8"))[0].model_copy(update={"rev": 2})
    patch = Patch(base_rev=2, author="ai", reason="test", ops=[PatchOp(op="set_fields", section_id="aaaa2", fields={"title": "AI"})])
    with pytest.raises(PatchRejected) as rejected:
        apply_patch(doc, patch)
    assert rejected.value.code == "owner-locked"


def test_D3_refusals_preserve_file_and_log(session):
    assert session is not None, "docla.server.app.create_app must exist"
    client, _, path, oplog = session
    assert _edit(client).json() == {"rev": 1}
    before = path.read_bytes(), oplog.read_bytes()
    current = client.get("/api/docs/deck").json()["document"]
    response = _edit(client, 0)
    assert response.status_code == 409
    assert response.json()["rev"] == 1 and response.json()["document"] == current
    assert (path.read_bytes(), oplog.read_bytes()) == before
    for fields in ({"intent": "quote"}, {"color": "red"}, {"owner": "ai"}):
        assert _edit(client, 1, fields=fields).status_code == 422
        assert (path.read_bytes(), oplog.read_bytes()) == before
    assert _edit(client, 1, section="zzzzz").status_code == 404
    assert (path.read_bytes(), oplog.read_bytes()) == before


def test_D4_add_and_delete_sections(session):
    assert session is not None, "docla.server.app.create_app must exist"
    client, _, path, _ = session
    response = client.post("/api/docs/deck/sections", json={"after_id": "aaaa1", "intent": "statement", "section": "content"})
    assert response.status_code == 200
    body = response.json()
    assert body["rev"] == 1 and re.fullmatch(r"[0-9a-f]{5}", body["id"])
    sections = parse(path.read_text(encoding="utf-8"))[0].sections
    assert [s.id for s in sections] == ["aaaa1", body["id"], "aaaa2"]
    assert sections[1].intent == "statement" and sections[1].section == "content"
    assert sections[1].title is None and sections[1].items == [] and sections[1].paragraphs == []
    response = client.post("/api/docs/deck/sections", json={"after_id": "aaaa1", "intent": "quote"})
    assert response.status_code == 200 and response.json()["rev"] == 2
    sections = parse(path.read_text(encoding="utf-8"))[0].sections
    assert sections[1].id == response.json()["id"] and sections[1].intent == "quote" and sections[1].section is None
    response = client.delete("/api/docs/deck/sections/aaaa2")
    assert response.status_code == 200 and response.json() == {"rev": 3}
    assert "aaaa2" not in [s.id for s in parse(path.read_text(encoding="utf-8"))[0].sections]
    assert client.delete("/api/docs/deck/sections/zzzzz").status_code == 404


def test_D5_success_and_refusal_events(session):
    assert session is not None, "docla.server.app.create_app must exist"
    client, app, _, _ = session
    assert app.state.bus.recent() == []
    responses = [_edit(client), client.post("/api/docs/deck/sections", json={"after_id": "aaaa1", "intent": "quote"}), client.delete("/api/docs/deck/sections/aaaa2")]
    assert [r.status_code for r in responses] == [200, 200, 200]
    assert [r.json()["rev"] for r in responses] == [1, 2, 3]
    expected = [{"type": "doc.changed", "data": {"doc": "deck", "rev": n, "by": "human"}} for n in (1, 2, 3)]
    assert app.state.bus.recent() == expected
    assert _edit(client, 0).status_code == 409
    assert _edit(client, 3, fields={"owner": "ai"}).status_code == 422
    assert client.delete("/api/docs/deck/sections/zzzzz").status_code == 404
    assert app.state.bus.recent() == expected


@pytest.mark.parametrize("operation", ["edit", "add", "delete_second", "delete_first"])
def test_D6_inverse_restores_canonical_bytes(session, operation):
    assert session is not None, "docla.server.app.create_app must exist"
    client, _, path, oplog = session
    before = path.read_bytes()
    if operation == "edit":
        response = _edit(client)
    elif operation == "add":
        response = client.post("/api/docs/deck/sections", json={"after_id": "aaaa1", "intent": "statement"})
    else:
        section = "aaaa2" if operation == "delete_second" else "aaaa1"
        response = client.delete(f"/api/docs/deck/sections/{section}")
    assert response.status_code == 200 and response.json()["rev"] == 1
    inverse = _lines(oplog)[-1]["inverse"]
    assert isinstance(inverse, list) and inverse
    patch = Patch(base_rev=current_rev(oplog), author="human", reason="undo", ops=[PatchOp.model_validate(op) for op in inverse])
    apply_to_file(path, patch, oplog, IdStore(oplog.parent / "ids.json"))
    assert path.read_bytes() == before
