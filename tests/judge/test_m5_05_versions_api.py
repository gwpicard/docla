# Intent: expose stored versions, their evidence and readiness through the authenticated visualiser API.
import hashlib
import importlib
import importlib.util
import json
import shutil

import pytest

from docla.checks.catalogue import all_rules
from docla.facts.layout import layout_facts
from docla.facts.raster import PdfiumRasteriser
from docla.model import Document, Finding, Section
from docla.render.compose import assemble, compose, font_paths
from docla.render.typst import compile_pdf
from docla.store import LookRecord, write_version
from docla.store.gate import ship_gate
from docla.theme import neutral_theme

try:
    server = importlib.import_module("docla.server.app")
except ImportError as error:
    if error.name not in ("docla.server", "docla.server.app"):
        raise
    if importlib.util.find_spec(error.name) is not None:
        raise
    server = None


@pytest.fixture
def client(tmp_path):
    if server is None or not hasattr(server, "create_app"):
        yield None
        return
    from fastapi.testclient import TestClient

    app = server.create_app(tmp_path, "test-token")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        client.headers.update({"X-Docla-Token": "test-token", "X-Token": "test-token", "Authorization": "Bearer test-token"})
        yield client


@pytest.fixture
def versions(tmp_path, client):
    if client is None:
        return None
    source = tmp_path / "deck.md"
    source.write_text("working document", encoding="utf-8")
    (tmp_path / "empty.md").write_text("working document", encoding="utf-8")
    doc = Document(front={"doctype": "pitch-deck"}, format="slides", sections=[
        Section(id="aaaa1", intent="statement", title="First slide"),
        Section(id="aaaa2", intent="statement", title="Second slide"),
    ])
    theme = neutral_theme()
    comp = compose(doc)
    root = tmp_path / "build"
    main = assemble(comp, root, theme=theme)
    fonts = font_paths(root)
    pdf = tmp_path / "input.pdf"
    compile_pdf(main, root, pdf, fonts)
    facts = layout_facts(pdf, main, root, font_paths=fonts)
    pngs = PdfiumRasteriser().render(pdf, tmp_path / "rendered")
    assert len(pngs) == 2
    findings = [Finding(id="known", rule_id="geo.text-fits", tier="geometry", severity="error",
                        format="slides", message="Too large", fingerprint="known",
                        remedy={"class": "report", "hint": "Review"}),
                Finding(id="unknown", rule_id="x.unknown", tier="source", severity="info",
                        format="slides", message="Unknown rule", fingerprint="unknown",
                        remedy={"class": "report", "hint": "Review"})]
    heal = tmp_path / "heal.jsonl"
    heal.write_text('{"event":"repair"}\n', encoding="utf-8")
    (tmp_path / "heal").mkdir()
    shutil.copyfile(pngs[0], tmp_path / "heal" / "aaaa1-1-before.png")
    first = write_version(source, doc, comp, pdf, facts, findings, pngs, heal, theme=theme)
    second = write_version(source, doc, comp, pdf, facts, [], pngs, None, theme=theme,
                           look=LookRecord(pages=2, clean=True))
    return first, second, heal


def test_D1_list_versions(client, versions):
    assert client is not None, "docla.server.app.create_app must exist"
    first, second, _ = versions
    response = client.get("/api/docs/deck/versions")
    assert response.status_code == 200
    manifests = [json.loads((version.path / "manifest.json").read_text()) for version in (first, second)]
    assert response.json() == {"versions": manifests}
    assert [item["version"] for item in response.json()["versions"]] == [1, 2]
    assert client.get("/api/docs/empty/versions").json() == {"versions": []}
    assert client.get("/api/docs/unknown/versions").status_code == 404


def test_D2_pages_and_findings(client, versions):
    assert client is not None, "docla.server.app.create_app must exist"
    first, _, _ = versions
    base = "/api/docs/deck/versions/1"
    pages = client.get(base + "/pages")
    assert pages.status_code == 200
    assert pages.json() == json.loads((first.path / "pages/pages.json").read_text())
    response = client.get(base + "/findings")
    assert response.status_code == 200
    findings = response.json()["findings"]
    assert [item["id"] for item in findings] == ["known", "unknown"]
    rule = next(rule for rule in all_rules() if rule.id == "geo.text-fits")
    assert findings[0]["remedy"]["class"] == "report"
    assert findings[0]["title"] == rule.title
    assert findings[0]["provenance"]["source"] == rule.provenance.model_dump(mode="json")["source"]
    assert findings[1]["title"] is None and findings[1]["provenance"] is None
    assert client.get("/api/docs/deck/versions/9/pages").status_code == 404
    assert client.get("/api/docs/deck/versions/9/findings").status_code == 404


def test_D3_page_images_cache(client, versions):
    assert client is not None, "docla.server.app.create_app must exist"
    first, _, _ = versions
    path = "/api/docs/deck/versions/1/page/1.png"
    data = (first.path / "pages/p01.png").read_bytes()
    etag = '"' + hashlib.sha256(data).hexdigest() + '"'
    response = client.get(path)
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content == data and response.headers["etag"] == etag
    cached = client.get(path, headers={"If-None-Match": etag})
    assert cached.status_code == 304 and cached.content == b""
    second = client.get("/api/docs/deck/versions/1/page/2.png")
    assert second.status_code == 200 and second.headers["etag"] != etag
    assert client.get("/api/docs/deck/versions/1/page/3.png").status_code == 404


def test_D4_heal_log_and_crops(client, versions):
    assert client is not None, "docla.server.app.create_app must exist"
    first, _, heal = versions
    base = "/api/docs/deck/versions/1/heal"
    response = client.get(base)
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == "application/x-ndjson"
    assert response.text == heal.read_text()
    data = (first.path / "heal/aaaa1-1-before.png").read_bytes()
    etag = '"' + hashlib.sha256(data).hexdigest() + '"'
    crop = client.get(base + "/aaaa1-1-before.png")
    assert crop.status_code == 200 and crop.headers["content-type"] == "image/png"
    assert crop.content == data and crop.headers["etag"] == etag
    cached = client.get(base + "/aaaa1-1-before.png", headers={"If-None-Match": etag})
    assert cached.status_code == 304 and cached.content == b""
    assert client.get(base + "/missing.png").status_code == 404
    assert client.get(base + "/..%2Fmanifest.png").status_code == 404
    assert client.get("/api/docs/deck/versions/2/heal").status_code == 404


def test_D5_ready_gate(client, versions):
    assert client is not None, "docla.server.app.create_app must exist"
    first, second, _ = versions
    reasons = ship_gate(first)
    assert reasons == ["not fully looked at", "1 error findings"]
    refused = client.post("/api/docs/deck/versions/1/ready")
    assert refused.status_code == 200 and refused.json() == {"ready": False, "reasons": reasons}
    assert json.loads((first.path / "manifest.json").read_text())["state"] == "draft"
    ready = client.post("/api/docs/deck/versions/2/ready")
    assert ready.status_code == 200 and ready.json() == {"ready": True, "reasons": []}
    assert json.loads((second.path / "manifest.json").read_text())["state"] == "ready"


def test_D6_routes_require_token(client, versions):
    assert client is not None, "docla.server.app.create_app must exist"
    client.headers.pop("X-Docla-Token")
    client.headers.pop("X-Token")
    client.headers.pop("Authorization")
    for method, path in [("GET", "/api/docs/deck/versions"),
                         ("GET", "/api/docs/deck/versions/1/pages"),
                         ("GET", "/api/docs/deck/versions/1/findings"),
                         ("GET", "/api/docs/deck/versions/1/page/1.png"),
                         ("GET", "/api/docs/deck/versions/1/heal"),
                         ("GET", "/api/docs/deck/versions/1/heal/aaaa1-1-before.png"),
                         ("POST", "/api/docs/deck/versions/1/ready")]:
        assert client.request(method, path).status_code == 401, path
