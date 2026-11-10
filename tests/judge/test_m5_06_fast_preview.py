# Intent: Accepted edits produce section previews and findings on the event stream.
import base64
import shutil
import time
from pathlib import Path

from docla.checks.catalogue import all_rules
from docla.source.parser import parse

try:
    import docla.server.app as server_app
except ImportError as error:
    if error.name not in ("docla.server", "docla.server.app"):
        raise
    server_app = None

try:
    import docla.server.preview as preview_module
except ImportError as error:
    if error.name not in ("docla.server", "docla.server.preview"):
        raise
    preview_module = None

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects" / "geo.text-fits"
DOC = '''---
doctype: report
format: doc
title: Note
---

## Sources

- [S1] workshop.vtt, transcript

::: {#bbbb1 .section intent="body"}
## Findings

The pipeline drops some readings, and the team agreed to measure how many. [S1 00:41]
:::
'''


def _app(project):
    assert server_app is not None and hasattr(server_app, "create_app"), "docla.server.app.create_app must exist"
    return server_app.create_app(project, "test-token")


def _client(app):
    from starlette.testclient import TestClient

    return TestClient(app, base_url="http://127.0.0.1:8765", headers={
        "X-Docla-Token": "test-token", "X-Token": "test-token", "Authorization": "Bearer test-token"
    })


def _patch(client, doc, section, rev, fields):
    return client.patch(f"/api/docs/{doc}/sections/{section}", json={"base_rev": rev, "fields": fields})


def _final(events, doc, section, rev):
    return [e for e in events if e["type"] == "section.state" and e["data"].get("doc") == doc
            and e["data"].get("id") == section and e["data"].get("rev") == rev
            and e["data"].get("state") in ("clean", "findings", "error")]


def _completed(bus, doc, section, rev, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = list(bus.recent())
        finals = _final(events, doc, section, rev)
        if finals and any(e["type"] == "look.progress" and e["data"] == {
            "doc": doc, "done": 1, "total": 1
        } for e in events[events.index(finals[-1]) + 1:]):
            return events
        time.sleep(0.01)
    assert False, f"Timed out waiting for preview events: {list(bus.recent())!r}"


def _png(data):
    assert isinstance(data["findings"], list)
    assert base64.b64decode(data["png"], validate=True).startswith(b"\x89PNG")


def _deck(tmp_path):
    shutil.copyfile(FIXTURES / "pass" / "doc.md", tmp_path / "deck.md")
    return _app(tmp_path)


def test_D1_warm_edit_publishes_ordered_preview_within_two_seconds(tmp_path):
    app = _deck(tmp_path)
    with _client(app) as client:
        warm = _patch(client, "deck", "c4e10", 0, {"title": "Warm up"})
        assert warm.status_code == 200, warm.text
        _completed(app.state.bus, "deck", "c4e10", warm.json()["rev"])
        response = _patch(client, "deck", "c4e10", warm.json()["rev"], {"title": "Updated title"})
        start = time.monotonic()
        assert response.status_code == 200, response.text
        rev = response.json()["rev"]
        events = _completed(app.state.bus, "deck", "c4e10", rev, timeout=2)
        assert time.monotonic() - start <= 2
        final = _final(events, "deck", "c4e10", rev)[-1]
        assert final["data"]["state"] in ("clean", "findings")
        _png(final["data"])
        assert any(e["type"] == "section.state" and e["data"] == {
            "doc": "deck", "id": "c4e10", "rev": rev, "state": "working"
        } for e in events[:events.index(final)])


def test_D2_overflow_finding_appears_and_disappears(tmp_path):
    app = _deck(tmp_path)
    fail, _ = parse((FIXTURES / "fail" / "doc.md").read_text())
    passing, _ = parse((FIXTURES / "pass" / "doc.md").read_text())
    assert len(fail.sections[0].items) == 9
    assert len(passing.sections[0].items) == 5
    with _client(app) as client:
        response = _patch(client, "deck", "c4e10", 0, {"items": [i.model_dump(mode="json") for i in fail.sections[0].items]})
        assert response.status_code == 200, response.text
        events = _completed(app.state.bus, "deck", "c4e10", response.json()["rev"])
        result = _final(events, "deck", "c4e10", response.json()["rev"])[-1]["data"]
        assert result["state"] == "findings"
        matches = [f for f in result["findings"] if f["rule_id"] == "geo.text-fits"]
        assert matches
        finding = matches[0]
        assert finding["severity"] == "error"
        assert "class" in finding["remedy"]
        assert finding["title"] == next(r.title for r in all_rules() if r.id == "geo.text-fits")
        response = _patch(client, "deck", "c4e10", response.json()["rev"], {"items": [i.model_dump(mode="json") for i in passing.sections[0].items]})
        assert response.status_code == 200, response.text
        events = _completed(app.state.bus, "deck", "c4e10", response.json()["rev"])
        result = _final(events, "deck", "c4e10", response.json()["rev"])[-1]["data"]
        assert result["state"] in ("clean", "findings")
        assert all(f["rule_id"] != "geo.text-fits" for f in result["findings"])


def test_D3_rejected_edits_emit_no_preview_events(tmp_path):
    app = _deck(tmp_path)
    with _client(app) as client:
        response = _patch(client, "deck", "c4e10", 0, {"title": "Accepted"})
        assert response.status_code == 200, response.text
        _completed(app.state.bus, "deck", "c4e10", response.json()["rev"])
        before = list(app.state.bus.recent())
        stale = _patch(client, "deck", "c4e10", 0, {"title": "Stale"})
        invalid = _patch(client, "deck", "c4e10", response.json()["rev"], {"items": "invalid"})
        assert stale.status_code == 409
        assert invalid.status_code == 422
        time.sleep(0.5)
        after = list(app.state.bus.recent())
        assert after[:len(before)] == before
        assert not any(e["type"] in ("section.state", "look.progress") for e in after[len(before):])


def test_D4_flow_sensitivity_and_document_preview(tmp_path):
    assert preview_module is not None and hasattr(preview_module, "flow_sensitive"), "docla.server.preview.flow_sensitive must exist"
    slides, _ = parse((FIXTURES / "pass" / "doc.md").read_text())
    doc, _ = parse(DOC)
    assert preview_module.flow_sensitive(slides, slides.sections[0]) is False
    assert preview_module.flow_sensitive(doc, doc.sections[0]) is True
    (tmp_path / "memo.md").write_text(DOC)
    app = _app(tmp_path)
    with _client(app) as client:
        response = _patch(client, "memo", "bbbb1", 0, {"title": "Revised findings"})
        assert response.status_code == 200, response.text
        events = _completed(app.state.bus, "memo", "bbbb1", response.json()["rev"])
        result = _final(events, "memo", "bbbb1", response.json()["rev"])[-1]["data"]
        assert result["state"] in ("clean", "findings")
        _png(result)
