# Intent: Ground brand voice and required elements in cited guidelines and notes.
import asyncio
import importlib
import importlib.util
import json
import shutil

import pytest
import yaml

from docla.agents.client import Claude
from docla.brand.workspace import init_brand
from docla.testing.fakes import FakeTransport, fake_response
from docla.theme import ThemeError, load_theme, neutral_theme
from docla.theme.voice import Term, load_voice


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        if importlib.util.find_spec(error.name) is not None:
            raise
        return None


synth = _module("docla.brand.synth_voice")
required = _module("docla.theme.required")


class Ledger:
    def add(self, role, model, usage):
        pass


def _client(*replies):
    transport = FakeTransport({"syn": [fake_response(json.dumps(reply)) for reply in replies]})
    return Claude(
        transport, Ledger(), {"brand.segment": "seg", "brand.extract": "ext", "brand.synthesise": "syn"}
    ), transport


def _brand(tmp_path):
    brand = init_brand("acme", tmp_path / ".brand")
    shutil.copytree(neutral_theme().root, brand / "theme", dirs_exist_ok=True)
    return brand


def _subject():
    assert synth is not None and hasattr(synth, "synthesise_voice"), "synthesise_voice must exist"
    return synth.synthesise_voice


def _required():
    assert required is not None and hasattr(required, "load_required"), "load_required must exist"
    return required.load_required


def _notes_brand(tmp_path, text):
    intake = _module("docla.brand.intake")
    assert intake is not None and hasattr(intake, "take_in"), "take_in must exist"
    brand = _brand(tmp_path)
    (brand / "materials/notes/notes.md").write_text(text, encoding="utf-8")
    intake.take_in(brand)
    return brand


def test_D1_no_sources_uses_neutral_voice_without_request(tmp_path):
    run = _subject()
    brand = _brand(tmp_path)
    client, transport = _client()
    asyncio.run(run(brand, client))
    assert transport.requests == []
    assert load_voice(load_theme(brand / "theme")) == load_voice(neutral_theme())


def test_D2_notes_ground_terms_and_summaries(tmp_path):
    run = _subject()
    brand = _notes_brand(tmp_path, "Do not write leverage. Write customer, never client.\n")
    source = "note:materials/notes/notes.md"
    reply = {
        "summary_slides": "Be direct.",
        "summary_doc": "Write plainly.",
        "banned": [{"term": "leverage", "source_id": source}, {"term": "blockchain", "source_id": source}],
        "terminology": [{"preferred": "customer", "avoid": ["client"], "source_id": source}],
        "required": [],
    }
    client, transport = _client(reply)
    result = asyncio.run(run(brand, client))
    voice = load_voice(load_theme(brand / "theme"))
    assert voice.banned == ["leverage"]
    assert voice.terminology == [Term(preferred="customer", avoid=["client"])]
    assert voice.summary == {"slides": "Be direct.", "doc": "Write plainly."}
    assert any(item["item"] == "blockchain" and item["reason"] == "not in source" for item in result.dropped)
    assert len(transport.requests) == 1 and transport.requests[0]["model"] == "syn"
    assert "Do not write leverage." in json.dumps(transport.requests[0]["messages"])


def test_D3_notes_required_elements_and_grounding(tmp_path):
    run = _subject()
    load = _required()
    brand = _notes_brand(tmp_path, "Every report names its author.\n")
    source = "note:materials/notes/notes.md"
    reply = {
        "summary_slides": None,
        "summary_doc": None,
        "banned": [],
        "terminology": [],
        "required": [
            {
                "element": "author",
                "name": "Author",
                "text": None,
                "place": None,
                "formats": ["doc"],
                "source_id": source,
            },
            {
                "element": "disclaimer",
                "name": "Disclaimer",
                "text": "Capital at risk.",
                "place": None,
                "formats": ["doc"],
                "source_id": source,
            },
        ],
    }
    client, _ = _client(reply)
    result = asyncio.run(run(brand, client))
    elements = load(load_theme(brand / "theme"))
    assert [(item.id, item.element, item.formats) for item in elements] == [("author", "author", ["doc"])]
    provenance = elements[0].provenance.model_dump(mode="json")
    assert provenance["label"].lower() == "measured"
    assert provenance["source"]["role"] == "notes"
    assert provenance["source"]["file"] == "materials/notes/notes.md"
    assert any(item["reason"] == "not in source" for item in result.dropped)


def test_D4_required_loader_rejects_duplicates_and_missing_provenance(tmp_path):
    load = _required()
    root = tmp_path / "theme"
    shutil.copytree(neutral_theme().root, root)
    theme = load_theme(root)
    assert load(theme) == []
    path = root / "required.yaml"
    author = {
        "id": "author",
        "element": "author",
        "name": "Author",
        "provenance": {
            "label": "measured",
            "source": {"file": "guide.pdf", "page": 1, "quote": "Name the author.", "role": "guidelines"},
            "by": "brand/synthesise",
        },
    }
    path.write_text(yaml.safe_dump({"elements": [author]}), encoding="utf-8")
    assert [item.id for item in load(theme)] == ["author"]
    path.write_text(yaml.safe_dump({"elements": [author, author]}), encoding="utf-8")
    with pytest.raises(ThemeError, match=r"^required\.yaml:"):
        load(theme)
    path.write_text(
        yaml.safe_dump({"elements": [{"id": "author", "element": "author", "name": "Author"}]}), encoding="utf-8"
    )
    with pytest.raises(ThemeError, match=r"^required\.yaml:"):
        load(theme)


def test_D5_no_source_synthesis_is_byte_identical_on_repeat(tmp_path):
    run = _subject()
    brand = _brand(tmp_path)
    client, transport = _client()
    asyncio.run(run(brand, client))
    paths = [brand / "theme/voice/terminology.yaml", brand / "theme/required.yaml", brand / "theme/ingest/voice.json"]
    before = [path.read_bytes() for path in paths]
    asyncio.run(run(brand, client))
    assert [path.read_bytes() for path in paths] == before
    assert transport.requests == []
