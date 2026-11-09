# Intent: preserve finished builds as immutable, indexed versions with a reviewable manifest schema.
import hashlib
import importlib
import importlib.util
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter

import docla
from docla.checks.catalogue import all_rules
from docla.checks.engine import CheckContext, run_checks
from docla.facts.layout import layout_facts
from docla.facts.raster import PdfiumRasteriser
from docla.model import Document, Finding, Section
from docla.model.schema import export_schemas
from docla.render.compose import assemble, compose, font_paths
from docla.render.typst import compile_pdf
from docla.theme import neutral_theme

try:
    store = importlib.import_module("docla.store")
except ImportError as error:
    if error.name != "docla.store" or importlib.util.find_spec("docla.store") is not None:
        raise
    store = None

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2025, 2, 3, 4, 5, 6, tzinfo=UTC)


def _store(*names):
    assert store is not None, "docla.store must exist"
    for name in names:
        assert hasattr(store, name), f"docla.store.{name} must exist"
    return store


@pytest.fixture
def deck(tmp_path):
    doc_path = tmp_path / "deck.md"
    doc_path.write_text("working document", encoding="utf-8")
    doc = Document(
        front={"doctype": "pitch-deck"},
        format="slides",
        rev=7,
        sections=[
            Section(id="aaaa1", intent="statement", title="First [GAP: owner name]"),
            Section(id="aaaa2", intent="statement", title="Second slide"),
        ],
    )
    theme = neutral_theme()
    comp = compose(doc)
    root = tmp_path / "build"
    main = assemble(comp, root, theme=theme)
    fonts = font_paths(root)
    pdf = tmp_path / "input.pdf"
    compile_pdf(main, root, pdf, fonts)
    facts = layout_facts(pdf, main, root, font_paths=fonts)
    findings = run_checks(all_rules(), CheckContext(doc, facts, theme=theme, composition=comp))
    findings.append(
        Finding(
            id="page-two",
            rule_id="test.page",
            tier="pixel",
            severity="info",
            format="slides",
            page=2,
            message="Page two",
            fingerprint="page-two",
            remedy={"class": "report", "hint": "Review"},
        )
    )
    pngs = PdfiumRasteriser().render(pdf, tmp_path / "rendered")
    assert len(pngs) == 2
    return doc_path, doc, comp, pdf, facts, findings, pngs, theme


def _write(deck, heal=None):
    doc_path, doc, comp, pdf, facts, findings, pngs, theme = deck
    return _store("write_version").write_version(
        doc_path, doc, comp, pdf, facts, findings, pngs, heal, theme=theme, now=lambda: NOW
    )


def _files(path):
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def test_D1_versions_copy_build_outputs_and_heal(deck, tmp_path):
    _store("write_version")
    heal = tmp_path / "heal.jsonl"
    heal.write_bytes(b'{"event":"repair"}\n')
    first = _write(deck, heal)
    second = _write(deck)
    assert (first.number, second.number) == (1, 2)
    assert first.path == tmp_path / "deck.versions" / "v1"
    assert second.path == tmp_path / "deck.versions" / "v2"
    for version in (first, second):
        files = _files(version.path)
        assert {
            "deck.pdf",
            "composition.json",
            "layout.json",
            "findings.json",
            "manifest.json",
            "pages/p01.png",
            "pages/p02.png",
            "pages/pages.json",
        } <= files.keys()
        assert files["deck.pdf"] == deck[3].read_bytes()
        assert json.loads(files["composition.json"]) == json.loads(deck[2].model_dump_json())
        assert json.loads(files["layout.json"]) == json.loads(deck[4].model_dump_json())
        assert json.loads(files["findings.json"]) == json.loads(TypeAdapter(list[Finding]).dump_json(deck[5]))
        assert files["pages/p01.png"] == deck[6][0].read_bytes()
        assert files["pages/p02.png"] == deck[6][1].read_bytes()
    assert (first.path / "heal.jsonl").read_bytes() == heal.read_bytes()
    assert not (second.path / "heal.jsonl").exists()


def test_D2_manifest_round_trip_and_gap(deck):
    api = _store("load_version")
    version = _write(deck)
    loaded = api.load_version(version.path)
    manifest = loaded.manifest
    assert (loaded.number, loaded.path, manifest.version) == (1, version.path, 1)
    assert (manifest.typst, manifest.engine, manifest.format, manifest.doctype) == (
        "0.15.1",
        docla.__version__,
        "slides",
        "pitch-deck",
    )
    assert (manifest.sections, manifest.doc_rev, manifest.outputs) == (2, 7, ["deck.pdf"])
    assert manifest.pdf_sha256 == hashlib.sha256(deck[3].read_bytes()).hexdigest() == deck[4].pdf_sha256
    assert (manifest.theme.name, manifest.theme.version) == ("neutral", deck[7].info.version)
    counts = Counter(f.severity for f in deck[5])
    assert manifest.findings.model_dump() == {key: counts[key] for key in ("error", "warning", "info")}
    assert (manifest.state, manifest.sent_to, manifest.final, manifest.draft) == ("draft", [], False, True)
    assert manifest.written == "2025-02-03T04:05:06Z"
    assert [gap.model_dump() for gap in manifest.gaps] == [{"section": "aaaa1", "text": "owner name"}]


def test_D3_page_index_matches_rendered_marks_and_findings(deck):
    api = _store("page_index")
    version = _write(deck)
    pages = json.loads((version.path / "pages/pages.json").read_text())["pages"]
    assert pages == api.page_index(deck[4], deck[5])
    assert len(pages) == 2
    for index, page in enumerate(pages):
        facts_page = deck[4].pages[index]
        assert (page["page"], page["image"], page["width"], page["height"]) == (
            index + 1,
            f"p{index + 1:02d}.png",
            facts_page.width,
            facts_page.height,
        )
        assert page["sections"] == [["aaaa1"], ["aaaa2"]][index]
        assert set(page) == {"page", "image", "width", "height", "sections", "regions", "findings"}
    assert pages[0]["regions"]
    assert all(region["section"] == "aaaa1" for region in pages[0]["regions"])
    assert all(set(region) == {"section", "role", "x", "y", "w", "h"} for page in pages for region in page["regions"])
    assert "page-two" not in pages[0]["findings"]
    assert "page-two" in pages[1]["findings"]


def test_D4_only_delivery_fields_change_and_versions_are_immutable(deck):
    api = _store("update_manifest", "load_version", "VersionImmutable")
    first = _write(deck)
    before = _files(first.path)
    _write(deck)
    assert _files(first.path) == before
    original = first.manifest.model_dump()
    updated = api.update_manifest(first.path, state="sent", sent_to=["board"])
    expected = {**original, "state": "sent", "sent_to": ["board"]}
    assert updated.model_dump() == expected
    assert api.load_version(first.path).manifest.model_dump() == expected
    manifest_path = first.path / "manifest.json"
    saved = manifest_path.read_bytes()
    for changes in ({"findings": {"error": 0, "warning": 0, "info": 0}}, {"pdf_sha256": "0"}):
        with pytest.raises(api.VersionImmutable):
            api.update_manifest(first.path, **changes)
        assert manifest_path.read_bytes() == saved


def test_D5_manifest_schema_export_matches_committed_file(tmp_path):
    api = _store("Manifest")
    try:
        schema = importlib.import_module("docla.store.schema")
    except ImportError as error:
        if error.name != "docla.store.schema" or importlib.util.find_spec("docla.store.schema") is not None:
            raise
        schema = None
    assert schema is not None and hasattr(schema, "export_manifest_schema")
    path = schema.export_manifest_schema(tmp_path)
    assert path == tmp_path / "Manifest.schema.json"
    assert list(tmp_path.iterdir()) == [path]
    expected = (
        json.dumps(api.Manifest.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()
    assert path.read_bytes() == expected
    assert (ROOT / "docs/schemas/store/Manifest.schema.json").read_bytes() == expected


def test_D6_existing_model_schemas_stay_unchanged(tmp_path):
    paths = export_schemas(tmp_path)
    expected_names = {"Document.schema.json", "Finding.schema.json", "Patch.schema.json", "Rule.schema.json"}
    assert {path.name for path in paths} == expected_names
    assert {path.name for path in tmp_path.glob("*.schema.json")} == expected_names
    committed = ROOT / "docs/schemas"
    assert {path.name for path in committed.glob("*.schema.json")} == expected_names
    for name in expected_names:
        assert (tmp_path / name).read_bytes() == (committed / name).read_bytes()
