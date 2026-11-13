# Intent: Each report uses its own brand theme for previews and builds.
import importlib
import importlib.util
import shutil
import time
from pathlib import Path

import pytest
from starlette.datastructures import State
from starlette.testclient import TestClient

from docla.source.parser import parse
from docla.theme import ThemeError, neutral_theme
from judge.test_m1_17_cli_build_check import DOC, SLIDES


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


server = _module("docla.server.app")
themes = _module("docla.server.themes")


def _project(tmp_path):
    brands = tmp_path / ".brand"
    theme = brands / "acme" / "theme"
    shutil.copytree(Path(__file__).resolve().parents[2] / "src/docla/themes/neutral", theme)
    voice = theme / "voice/terminology.yaml"
    voice.write_text(voice.read_text().replace("banned: [", "banned: [pilot, "))
    project = brands / "acme/reports/q3"
    project.mkdir(parents=True)
    return project, brands, theme


def _themed(text, name):
    return text.replace("format:", f"theme: {name}\nformat:", 1)


def _app(project, **kwargs):
    assert server is not None and hasattr(server, "create_app"), "create_app must exist"
    return server.create_app(project, "test-token", **kwargs)


def _client(app):
    return TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Docla-Token": "test-token"})


def _patch(client, doc, section, fields):
    response = client.patch(f"/api/docs/{doc}/sections/{section}", json={"base_rev": 0, "fields": fields})
    assert response.status_code == 200, response.text
    assert response.json()["rev"] == 1
    return response.json()["rev"]


def _final(bus, doc, section, rev):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for event in reversed(list(bus.recent())):
            data = event["data"]
            if (event["type"] == "section.state" and data.get("doc") == doc
                    and data.get("id") == section and data.get("rev") == rev
                    and data.get("state") in ("clean", "findings", "error")):
                return data
        time.sleep(0.02)
    pytest.fail(f"Timed out waiting for preview: {list(bus.recent())!r}")


def test_D1_document_theme_resolves_neutral_brand_and_errors(tmp_path):
    assert themes is not None and hasattr(themes, "document_theme"), "document_theme must exist"
    _, brands, root = _project(tmp_path)
    neutral = neutral_theme()
    state = State({"theme": neutral, "brands": brands})
    for text in (SLIDES, _themed(SLIDES, "neutral"), _themed(SLIDES, '\"\"')):
        assert themes.document_theme(state, parse(text)[0]) is neutral
    assert themes.document_theme(state, parse(_themed(SLIDES, "acme"))[0]).root == root
    for name in ("nobrand", '\"../acme\"'):
        with pytest.raises(ThemeError) as error:
            themes.document_theme(state, parse(_themed(SLIDES, name))[0])
        assert name.strip('\"') in str(error.value)


def test_D2_branded_and_neutral_slide_previews(tmp_path):
    project, brands, _ = _project(tmp_path)
    (project / "deck.md").write_text(_themed(SLIDES, "acme"))
    (project / "plain.md").write_text(SLIDES)
    app = _app(project)
    assert hasattr(app.state, "brands"), "create_app must set state.brands"
    assert app.state.brands == brands.resolve()
    with _client(app) as client:
        for name, expected in (("deck", True), ("plain", False)):
            rev = _patch(client, name, "aaaa1", {"title": "One pilot is plenty"})
            result = _final(app.state.bus, name, "aaaa1", rev)
            assert result["state"] in ("clean", "findings"), result
            assert any(f["rule_id"] == "source.banned-terms" for f in result["findings"]) is expected


def test_D3_branded_document_flow_preview(tmp_path):
    project, _, _ = _project(tmp_path)
    (project / "memo.md").write_text(_themed(DOC, "acme"))
    app = _app(project)
    with _client(app) as client:
        rev = _patch(client, "memo", "bbbb1", {"paragraphs": ["One pilot is enough."]})
        result = _final(app.state.bus, "memo", "bbbb1", rev)
        assert result["state"] == "findings", result
        assert any(f["rule_id"] == "source.banned-terms" for f in result["findings"])


def test_D4_missing_brand_reports_preview_and_build_errors(tmp_path):
    project, _, _ = _project(tmp_path)
    (project / "deck.md").write_text(_themed(SLIDES, "nobrand"))
    app = _app(project, agents=object())
    with _client(app) as client:
        rev = _patch(client, "deck", "aaaa1", {"title": "Updated title"})
        result = _final(app.state.bus, "deck", "aaaa1", rev)
        assert result["state"] == "error", result
        assert "nobrand" in result["message"]
        response = client.post("/api/docs/deck/build", json={"mode": "draft"})
        assert response.status_code == 202, response.text
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            job = app.state.jobs.get(response.json()["job"])
            assert job is not None
            if job.status != "running":
                break
            time.sleep(0.02)
        assert job.status == "failed"
        assert "nobrand" in job.error


def test_D5_default_theme_stays_neutral(tmp_path):
    (tmp_path / "deck.md").write_text(SLIDES)
    app = _app(tmp_path)
    assert app.state.theme.info.name == "neutral"
