# Intent: Keep only typed brand claims supported by their cited pages.
import asyncio
import hashlib
import importlib
import importlib.util
import json
import subprocess
from pathlib import Path

from docla import cli
from docla.agents.client import Claude
from docla.brand.workspace import init_brand
from docla.render.typst import compile_pdf
from docla.testing.fakes import FakeTransport, fake_response


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        if importlib.util.find_spec(error.name) is not None:
            raise
        return None


claims = _module("docla.brand.claims")
agents = _module("docla.brand.agents")
intake = _module("docla.brand.intake")
pages = _module("docla.brand.pages")
segment = _module("docla.brand.segment")
changes = _module("docla.brand.changes")

FILE = "materials/guidelines/book.pdf"
FONTS = Path(__file__).resolve().parents[2] / "src/docla/themes/neutral/fonts"
QUOTE = 'Our primary colour is "Acme Blue", #0B5FFF.'
TYPST = (
    "#set page(width: 960pt, height: 540pt)\n"
    '#set text(font: "Inter")\n'
    'Our primary colour is "Acme Blue", \\#0B5FFF.\n\n'
    "Titles must always use Acme Blue.\n"
    "#pagebreak()\n"
    "Body text is set at 11 pt.\n"
    "#pagebreak()\n"
    "Never stretch the logo.\n"
)


def _require(module, label, *names):
    assert module is not None, f"{label} must exist"
    for name in names:
        assert hasattr(module, name), f"{label}.{name} must exist"
    return module


def _api(*names):
    return _require(claims, "docla.brand.claims", *names)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _brand(tmp_path, *, topics=True):
    _require(intake, "docla.brand.intake", "take_in")
    _require(pages, "docla.brand.pages", "parse_pdfs")
    _require(segment, "docla.brand.segment", "TopicMap", "TOPICS")
    brand = init_brand("acme", tmp_path / ".brand")
    source = brand / "input.typ"
    source.write_text(TYPST)
    (brand / FILE).parent.mkdir(parents=True, exist_ok=True)
    compile_pdf(source, brand, brand / FILE, [FONTS])
    source.unlink()
    intake.take_in(brand)
    pages.parse_pdfs(brand)
    if topics:
        _write_topics(brand)
    return brand


def _write_topics(brand):
    topic_map = segment.TopicMap.model_validate(
        {
            "schema_version": 1,
            "files": [
                {
                    "file": FILE,
                    "sha256": _sha(brand / FILE),
                    "formats": ["slides"],
                    "pages": [
                        {"page": 1, "topics": ["colour"]},
                        {"page": 2, "topics": ["colour", "typography"]},
                        {"page": 3, "topics": ["logo"]},
                    ],
                    "missing": [],
                }
            ],
        }
    )
    path = brand / segment.TOPICS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(topic_map.model_dump_json(indent=2) + "\n")


class Ledger:
    def add(self, role, model, usage):
        pass


def _claude(replies):
    transport = FakeTransport({"ext": [fake_response(json.dumps({"claims": reply})) for reply in replies]})
    return Claude(transport, Ledger(), {"brand.segment": "seg", "brand.extract": "ext"}), transport


def _src(quote, page=1, visual=False, bbox=None):
    return {"file": FILE, "page": page, "quote": quote, "visual": visual, "bbox": bbox}


def _c(statement, sources, kind="rule", values=()):
    return {
        "kind": kind,
        "statement": statement,
        "values": [{"name": "value", "value": value} for value in values],
        "strength": "hard",
        "formats": [],
        "sources": sources,
        "confidence": 0.9,
        "check_hint": None,
    }


COLOUR = [
    _c("Primary colour is Acme Blue", [_src(QUOTE)], kind="token", values=["#0B5FFF"]),
    _c("Titles use Acme Blue", [_src("Titles must always   use Acme Blue")]),
    _c("Accent is red", [_src("Our accent colour is red.")]),
    _c("Logo is never stretched here", [_src("Never stretch the logo.", page=3)]),
    _c("Primary colour is red", [_src(QUOTE)], kind="token", values=["#FF0000"]),
    _c("Unsourced claim", []),
    _c("Mark reads ACME MARK", [_src("ACME MARK", visual=True, bbox=[100, 100, 300, 200])]),
    _c("Mark without box", [_src("ACME MARK", visual=True, bbox=None)]),
    _c("Mark outside page", [_src("ACME MARK", visual=True, bbox=[100, 100, 2000, 200])]),
]
TYPOGRAPHY = [
    _c("Body text is 11 pt", [_src("Body text is set at 11 pt.", page=2)], values=["11pt"]),
    _c("Body text is 12 pt", [_src("Body text is set at 11 pt.", page=2)], values=["12pt"]),
]
LOGO = [_c("Never stretch the logo", [_src("Never stretch the logo.", page=3)])]


def _run(brand, replies=(COLOUR, TYPOGRAPHY, LOGO), **kwargs):
    claude, transport = _claude(replies)
    try:
        result = asyncio.run(claims.extract_claims(brand, claude, **kwargs))
    except AssertionError:
        raise
    except Exception as error:
        raise AssertionError(f"extract_claims raised {error!r}") from None
    return result, transport


def _texts(request):
    blocks = request["messages"][0]["content"]
    return blocks, "\n".join(block["text"] for block in blocks if block["type"] == "text")


def _kept(result, statement):
    found = [claim for claim in result.claims if claim.statement == statement]
    assert len(found) == 1, f"{statement!r} must be kept once"
    return found[0]


def _dropped(result, statement):
    return [claim.reason for claim in result.dropped if claim.statement == statement]


def test_D1_one_request_per_topic_batch(tmp_path):
    _api("extract_claims")
    brand = _brand(tmp_path)
    _, transport = _run(brand)
    assert len(transport.requests) == 3
    firsts = []
    for request in transport.requests:
        assert request["model"] == "ext"
        blocks, _ = _texts(request)
        firsts.append(blocks[0])
    assert [block.get("text") for block in firsts] == ["TOPIC: colour", "TOPIC: typography", "TOPIC: logo"]
    colour_blocks, colour_text = _texts(transport.requests[0])
    assert colour_blocks[0]["type"] == "text"
    assert sum(block["type"] == "image" for block in colour_blocks) == 2
    assert f'<page file="{FILE}" number="1">' in colour_text
    assert f'<page file="{FILE}" number="2">' in colour_text
    logo_blocks, logo_text = _texts(transport.requests[2])
    assert sum(block["type"] == "image" for block in logo_blocks) == 1
    assert f'<page file="{FILE}" number="3">' in logo_text
    assert f'<page file="{FILE}" number="1">' not in logo_text
    assert f'<page file="{FILE}" number="2">' not in logo_text


def test_D1_batch_size_one_splits_colour(tmp_path):
    _api("extract_claims")
    brand = _brand(tmp_path)
    _, transport = _run(brand, replies=([], [], [], []), batch_size=1)
    assert len(transport.requests) == 4
    firsts = [_texts(request)[0][0].get("text") for request in transport.requests]
    assert firsts == ["TOPIC: colour", "TOPIC: colour", "TOPIC: typography", "TOPIC: logo"]


def test_D2_supported_claims_are_kept_as_text(tmp_path):
    _api("extract_claims")
    brand = _brand(tmp_path)
    result, _ = _run(brand)
    token = _kept(result, "Primary colour is Acme Blue")
    assert token.kind == "token"
    assert [value.value for value in token.values] == ["#0B5FFF"]
    assert [source.found for source in token.sources] == ["text"]
    assert token.sources[0].quote == QUOTE
    rule = _kept(result, "Titles use Acme Blue")
    assert [source.found for source in rule.sources] == ["text"]


def test_D2_unsupported_claims_are_dropped_with_reason(tmp_path):
    _api("extract_claims")
    brand = _brand(tmp_path)
    result, _ = _run(brand)
    kept = {claim.statement for claim in result.claims}
    expected = {
        "Accent is red": "quote not found",
        "Logo is never stretched here": "page not sent",
        "Primary colour is red": "value not in quote",
        "Unsourced claim": "no source",
    }
    for statement, reason in expected.items():
        assert statement not in kept
        assert _dropped(result, statement) == [reason]


def test_D3_visual_sources_need_a_valid_box(tmp_path):
    _api("extract_claims")
    brand = _brand(tmp_path)
    result, _ = _run(brand)
    mark = _kept(result, "Mark reads ACME MARK")
    assert [source.found for source in mark.sources] == ["visual"]
    assert list(mark.sources[0].bbox) == [100, 100, 300, 200]
    kept = {claim.statement for claim in result.claims}
    for statement in ("Mark without box", "Mark outside page"):
        assert statement not in kept
        assert _dropped(result, statement) == ["visual source without a valid box"]


def test_D3_numbers_must_appear_in_the_quote(tmp_path):
    _api("extract_claims")
    brand = _brand(tmp_path)
    result, _ = _run(brand)
    body = _kept(result, "Body text is 11 pt")
    assert [source.found for source in body.sources] == ["text"]
    assert "Body text is 12 pt" not in {claim.statement for claim in result.claims}
    assert _dropped(result, "Body text is 12 pt") == ["value not in quote"]


def test_D4_normalise_and_stable_claim_id():
    api = _api("normalise", "claim_id", "ClaimSource")
    result = api.normalise("Use  \u201cAcme Blue\u201d\nfor titles \u2014 always")
    assert result == 'use "acme blue" for titles - always'
    source = api.ClaimSource.model_validate(_src(QUOTE))
    expected = "c-e0dce7b0b7de"
    assert api.claim_id("colour", "token", "Primary Blue", [source]) == expected
    assert api.claim_id("colour", "token", "PRIMARY BLUE", [source]) == expected


def test_D4_topics_ids_and_stored_claim_set(tmp_path):
    _api("extract_claims", "ClaimSet", "CLAIMS")
    brand = _brand(tmp_path)
    result, _ = _run(brand)
    topics = {claim.statement: claim.topic for claim in result.claims}
    assert topics["Primary colour is Acme Blue"] == "colour"
    assert topics["Body text is 11 pt"] == "typography"
    assert topics["Never stretch the logo"] == "logo"
    assert all(claim.id.startswith("c-") for claim in result.claims)
    path = brand / claims.CLAIMS
    first = path.read_bytes()
    stored = claims.ClaimSet.model_validate_json(first)
    assert stored == result
    reasons = {claim.statement: claim.reason for claim in stored.dropped}
    assert reasons["Accent is red"] == "quote not found"
    assert reasons["Unsourced claim"] == "no source"
    _run(brand)
    assert path.read_bytes() == first


def test_D4_same_claim_from_two_batches_is_kept_once(tmp_path):
    _api("extract_claims")
    brand = _brand(tmp_path)
    token = COLOUR[0]
    result, transport = _run(brand, replies=([token], [token], [], []), batch_size=1)
    assert len(transport.requests) == 4
    kept = [claim for claim in result.claims if claim.statement == token["statement"]]
    assert len(kept) == 1
    assert len({claim.id for claim in result.claims}) == len(result.claims)


def _git(brand, *args):
    return subprocess.run(["git", *args], cwd=brand, check=True, capture_output=True, text=True).stdout.strip()


def _commit(brand):
    subprocess.run(["git", "add", "-A"], cwd=brand, check=True)
    subprocess.run(
        ["git", "-c", "user.name=docla", "-c", "user.email=docla@localhost", "commit", "-m", "Prepare materials"],
        cwd=brand,
        check=True,
        capture_output=True,
    )


def _main(args):
    try:
        return cli.main(args)
    except SystemExit as error:
        return error.code


def test_D5_cli_extracts_and_records_change(tmp_path, monkeypatch, capsys):
    _api("extract_claims")
    _require(agents, "docla.brand.agents", "brand_claude")
    _require(changes, "docla.brand.changes", "change_log")
    brand = _brand(tmp_path)
    _commit(brand)
    claude, _ = _claude((COLOUR, TYPOGRAPHY, LOGO))
    monkeypatch.setattr(agents, "brand_claude", lambda path: claude)
    root = tmp_path / ".brand"
    assert _main(["brand", "extract", "acme", "--root", str(root)]) == 0
    assert "claims kept" in capsys.readouterr().out
    assert _git(brand, "branch", "--show-current") == "main"
    assert _git(brand, "status", "--porcelain") == ""
    records = [record for record in changes.change_log(brand) if record.what == "Extract the guidelines' claims"]
    assert len(records) == 1
    assert any(item.page == 1 and item.quote == QUOTE for item in records[0].evidence)


def test_D5_missing_topic_map_returns_2(tmp_path, monkeypatch):
    _api("extract_claims")
    _require(agents, "docla.brand.agents", "brand_claude")
    brand = _brand(tmp_path, topics=False)
    _commit(brand)
    claude, transport = _claude(())
    monkeypatch.setattr(agents, "brand_claude", lambda path: claude)
    head = _git(brand, "rev-parse", "HEAD")
    assert _main(["brand", "extract", "acme", "--root", str(tmp_path / ".brand")]) == 2
    assert _git(brand, "rev-parse", "HEAD") == head
    assert _git(brand, "branch", "--show-current") == "main"
    assert _git(brand, "status", "--porcelain") == ""
    assert transport.requests == []
