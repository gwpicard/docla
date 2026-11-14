# Intent: Tie stated brand claims to grounded, format-compatible token values.
import asyncio
import importlib
import importlib.util
import json

import pytest

from docla import cli
from docla.agents.client import Claude
from docla.brand.git import run_git
from docla.brand.workspace import init_brand
from docla.testing.fakes import FakeTransport, fake_response


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        if importlib.util.find_spec(name) is not None:
            raise
        return None


tokenmap = _module("docla.brand.tokenmap")
claims = _module("docla.brand.claims")


def _api(*names):
    assert tokenmap is not None, "docla.brand.tokenmap must exist"
    for name in names:
        assert hasattr(tokenmap, name), f"docla.brand.tokenmap.{name} must exist"
    return tokenmap


class Ledger:
    def add(self, role, model, usage):
        pass


def _claude(replies):
    transport = FakeTransport({"ext": [fake_response(json.dumps(reply)) for reply in replies]})
    return Claude(transport, Ledger(), {"brand.segment": "seg", "brand.extract": "ext"}), transport


def _reply():
    return {
        "ties": [
            {"claim_id": c, "path": p, "value": v, "reason": "stated"}
            for c, p, v in [
                ("c-1", "colour.roles.accent", "#0B5FFF"),
                ("c-2", "type.scale.doc.body.size", "11 pt"),
                ("c-3", "pages.slides.margin.left", "20 mm"),
                ("c-3", "pages.doc.margin.left", "20 mm"),
                ("c-1", "colour.roles.ink", "#FF0000"),
                ("c-2", "type.scale.doc.body.size", "11 pt"),
                ("c-2", "type.scale.doc.nonesuch.size", "11"),
            ]
        ]
    }


def _brand(tmp_path):
    assert claims is not None and hasattr(claims, "ClaimSet"), "B.07 ClaimSet must exist"
    brand = init_brand("acme", tmp_path / ".brand")
    rows = [
        (
            "c-1",
            "token",
            [],
            "Acme Blue is our primary colour",
            [("hex", "#0B5FFF"), ("name", "Acme Blue")],
            "Acme Blue #0B5FFF",
            False,
        ),
        (
            "c-2",
            "rule",
            ["doc"],
            "Body copy is set at 11 pt in reports",
            [("size", "11 pt")],
            "Body copy is set at 11 pt in reports",
            False,
        ),
        (
            "c-3",
            "token",
            ["slides"],
            "Slide margins are 20 mm",
            [("margin", "20 mm")],
            "Slide margins are 20 mm",
            False,
        ),
        ("c-4", "token", [], "Process colour", [("cmyk", "100 60 0 0")], "Process: C100 M60 Y0 K0", False),
        ("c-5", "rule", [], "Use real people", [], "Use real people", False),
        ("c-6", "token", [], "Example red", [("hex", "#E4002B")], "#E4002B", True),
    ]
    data = []
    for ident, kind, formats, statement, values, quote, illustrative in rows:
        data.append(
            {
                "id": ident,
                "topic": "colour",
                "kind": kind,
                "formats": formats,
                "statement": statement,
                "values": [{"name": n, "value": v} for n, v in values],
                "strength": "soft" if illustrative else "hard",
                "confidence": 0.9,
                "check_hint": None,
                "illustrative": illustrative,
                "illustrative_reason": "shown" if illustrative else None,
                "sources": [
                    {
                        "file": "materials/guidelines/book.pdf",
                        "page": 1,
                        "quote": quote,
                        "found": "text",
                        "visual": False,
                        "bbox": None,
                    }
                ],
            }
        )
    field = "claims" if "claims" in claims.ClaimSet.model_fields else "items"
    claimset = claims.ClaimSet.model_validate({field: data})
    path = brand / "theme/ingest/claims.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(claimset.model_dump_json(indent=2) + "\n")
    return brand, data


def test_D1_targets_and_formats():
    m = _api("token_targets", "path_format")
    targets = m.token_targets()
    assert targets == sorted(targets)
    assert {
        "colour.roles.accent",
        "colour.roles.surface-alt",
        "type.families.text.name",
        "type.scale.slides.title.size",
        "type.scale.doc.h1.size",
        "type.scale.doc.min_size",
        "pages.doc.margin.top",
        "pages.doc.columns",
        "imagery.min_dpi",
    } <= set(targets)
    assert not any(p.startswith(("colour.usage", "spacing")) for p in targets)
    assert m.path_format("pages.doc.margin.top") == "doc"
    assert m.path_format("type.scale.slides.body.size") == "slides"
    assert m.path_format("colour.roles.accent") is None


def test_D2_requests_and_accepted_values(tmp_path):
    m = _api("tie_claims")
    brand, data = _brand(tmp_path)
    client, transport = _claude([_reply()])
    result = asyncio.run(m.tie_claims(brand, client))
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request["model"] == "ext"
    content = json.dumps(request["messages"])
    assert "colour.roles.accent" in content and "Acme Blue #0B5FFF" in content
    assert "c-5" not in content and "c-6" not in content
    items = result.items
    assert [(i.path, i.format, i.claim_id) for i in items] == [
        ("colour.roles.accent", None, "c-1"),
        ("pages.slides.margin.left", "slides", "c-3"),
        ("type.scale.doc.body.size", "doc", "c-2"),
    ]
    assert items[0].value == "#0B5FFF"
    assert items[1].value == pytest.approx(56.69, abs=0.01)
    assert items[2].value == 11.0
    by_id = {row["id"]: row for row in data}
    for item in items:
        assert item.source.quote == by_id[item.claim_id]["sources"][0]["quote"]
        assert item.strength == by_id[item.claim_id]["strength"]


def test_D3_refusals_and_untied(tmp_path):
    m = _api("tie_claims", "check_tie", "TokenTie")
    brand, data = _brand(tmp_path)
    client, _ = _claude([_reply()])
    result = asyncio.run(m.tie_claims(brand, client))
    assert {(r.claim_id, r.path, r.reason) for r in result.refused} == {
        ("c-3", "pages.doc.margin.left", "wrong format"),
        ("c-1", "colour.roles.ink", "value not in claim"),
        ("c-2", "type.scale.doc.nonesuch.size", "unknown token"),
    }
    assert result.untied == ["c-4"]
    claim = claims.Claim.model_validate(data[2])
    tie = m.TokenTie(claim_id="c-3", path="pages.slides.width", value="wide", reason="stated")
    assert m.check_tie(tie, claim) == "bad value"


def test_D4_persistence_and_batches(tmp_path):
    m = _api("tie_claims", "TokenClaims", "load_token_claims")
    brand, _ = _brand(tmp_path)
    client, _ = _claude([_reply(), _reply()])
    result = asyncio.run(m.tie_claims(brand, client))
    path = brand / "theme/ingest/token-claims.json"
    before = path.read_bytes()
    assert before.endswith(b"\n")
    assert m.TokenClaims.model_validate_json(before) == result == m.load_token_claims(brand)
    assert asyncio.run(m.tie_claims(brand, client)) == result
    assert path.read_bytes() == before
    client, transport = _claude([{"ties": []}, {"ties": []}])
    asyncio.run(m.tie_claims(brand, client, batch_size=2))
    assert len(transport.requests) == 2


def test_D5_cli_records_change_and_rejects_missing_claims(tmp_path, monkeypatch, capsys):
    _api("tie_claims")
    brand, _ = _brand(tmp_path)
    run_git(brand, "add", "-A")
    run_git(brand, "commit", "-m", "Prepare claims")
    agents = _module("docla.brand.agents")
    assert agents is not None and hasattr(agents, "brand_claude")
    client, _ = _claude([_reply()])
    monkeypatch.setattr(agents, "brand_claude", lambda brand: client)
    assert cli.main(["brand", "tie", "acme", "--root", str(brand.parent)]) == 0
    assert "3 token values" in capsys.readouterr().out
    assert run_git(brand, "branch", "--show-current").strip() == "main"
    assert run_git(brand, "status", "--porcelain") == ""
    records = [json.loads(p.read_text()) for p in brand.rglob("*.json") if ".git" not in p.parts]
    assert any(isinstance(r, dict) and r.get("what") == "Tie the guidelines' claims to tokens" for r in records)
    missing = init_brand("missing", brand.parent)
    assert cli.main(["brand", "tie", "missing", "--root", str(brand.parent)]) == 2
    assert run_git(missing, "branch", "--show-current").strip() == "main"
    assert run_git(missing, "status", "--porcelain") == ""
