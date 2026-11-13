# Intent: Keep illustrated examples from becoming rules without a person's confirmation.
import asyncio
import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image

from docla import cli
from docla.agents.client import Claude
from docla.brand.workspace import init_brand
from docla.render.typst import compile_pdf
from docla.testing.fakes import FakeTransport, fake_response


def _subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        if importlib.util.find_spec(error.name) is not None:
            raise
        return None


claims = _subject("docla.brand.claims")
illustrative = _subject("docla.brand.illustrative")
agents = _subject("docla.brand.agents")
intake = _subject("docla.brand.intake")
pages = _subject("docla.brand.pages")
segment = _subject("docla.brand.segment")
questions = _subject("docla.brand.questions")

ROOT = Path(__file__).resolve().parents[2]
FILE = "materials/guidelines/book.pdf"
FONTS = ROOT / "src/docla/themes/neutral/fonts"
OVER_IMAGE = [500, 220, 700, 330]
TYPST = (
    "#set page(width: 960pt, height: 540pt, "
    'background: place(top + left, dx: 480pt, dy: 200pt, image("photo.png", width: 300pt)))\n'
    '#set text(font: "Inter")\n'
    "Use photos of real people.\n"
)


def _require(module, label, *names):
    assert module is not None, f"{label} must exist"
    for name in names:
        assert hasattr(module, name), f"{label}.{name} must exist"
    return module


def _brand(tmp_path):
    _require(intake, "docla.brand.intake", "take_in")
    _require(pages, "docla.brand.pages", "parse_pdfs")
    _require(segment, "docla.brand.segment", "TopicMap", "TOPICS")
    brand = init_brand("acme", tmp_path / ".brand")
    Image.new("RGB", (200, 100), (30, 90, 200)).save(brand / "photo.png")
    source = brand / "input.typ"
    source.write_text(TYPST)
    (brand / FILE).parent.mkdir(parents=True, exist_ok=True)
    compile_pdf(source, brand, brand / FILE, [FONTS])
    source.unlink()
    (brand / "photo.png").unlink()
    intake.take_in(brand)
    pages.parse_pdfs(brand)
    topic_map = segment.TopicMap.model_validate(
        {
            "schema_version": 1,
            "files": [
                {
                    "file": FILE,
                    "sha256": hashlib.sha256((brand / FILE).read_bytes()).hexdigest(),
                    "formats": ["slides"],
                    "pages": [{"page": 1, "topics": ["imagery"]}],
                    "missing": [],
                }
            ],
        }
    )
    path = brand / segment.TOPICS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(topic_map.model_dump_json(indent=2) + "\n")
    return brand


class Ledger:
    def add(self, role, model, usage):
        pass


def _claude(replies):
    transport = FakeTransport({"ext": [fake_response(json.dumps({"claims": reply})) for reply in replies]})
    return Claude(transport, Ledger(), {"brand.segment": "seg", "brand.extract": "ext"}), transport


def _src(quote, *, visual=False, bbox=None):
    return {"file": FILE, "page": 1, "quote": quote, "visual": visual, "bbox": bbox}


def _c(statement, sources, *, basis=None, formats=()):
    claim = {
        "kind": "rule",
        "statement": statement,
        "values": [],
        "strength": "hard",
        "formats": list(formats),
        "sources": sources,
        "confidence": 0.9,
        "check_hint": None,
    }
    if basis is not None:
        claim["basis"] = basis
    return claim


STATED = _c("Use photos of real people.", [_src("Use photos of real people.")])
SHOWN = _c("Crop photos to a square.", [_src("SQUARE CROP", visual=True, bbox=OVER_IMAGE)], basis="shown")
IMAGE = _c("Photos carry the ACME tag.", [_src("ACME TAG", visual=True, bbox=OVER_IMAGE)], basis="stated")
OUTSIDE = _c("The footer reads ACME.", [_src("ACME", visual=True, bbox=[50, 400, 250, 500])], basis="stated")
MIXED = _c(
    "Real people carry the tag.",
    [_src("ACME TAG", visual=True, bbox=OVER_IMAGE), _src("Use photos of real people.")],
    basis="stated",
)
ALL = [STATED, SHOWN, IMAGE, OUTSIDE, MIXED]


def _extract(brand, reply):
    _require(claims, "docla.brand.claims", "extract_claims")
    claude, _ = _claude([reply])
    try:
        return asyncio.run(claims.extract_claims(brand, claude))
    except AssertionError:
        raise
    except Exception as error:
        raise AssertionError(f"extract_claims raised {error!r}") from None


def _kept(result, statement):
    found = [claim for claim in result.claims if claim.statement == statement]
    assert len(found) == 1, f"{statement!r} must be kept once"
    return found[0]


def _claim(statement, *, claim_id, formats, basis="stated", illustrative_value=False, reason=None):
    _require(claims, "docla.brand.claims", "Claim")
    return claims.Claim.model_validate(
        {
            "id": claim_id,
            "topic": "imagery",
            "kind": "rule",
            "statement": statement,
            "values": [],
            "strength": "soft" if illustrative_value else "hard",
            "formats": formats,
            "sources": [
                {
                    "file": FILE,
                    "page": 1,
                    "quote": statement,
                    "visual": True,
                    "bbox": OVER_IMAGE,
                    "found": "visual",
                }
            ],
            "confidence": 0.9,
            "check_hint": None,
            "basis": basis,
            "illustrative": illustrative_value,
            "illustrative_reason": reason,
        }
    )


def test_D1_stated_and_shown_claims(tmp_path):
    brand = _brand(tmp_path)
    result = _extract(brand, ALL)
    stated = _kept(result, STATED["statement"])
    assert stated.basis == "stated"
    assert stated.illustrative is False
    shown = _kept(result, SHOWN["statement"])
    assert shown.basis == "shown"
    assert shown.illustrative is True
    assert shown.illustrative_reason == "shown"
    assert shown.strength == "soft"


def test_D2_claims_read_only_inside_an_image(tmp_path):
    brand = _brand(tmp_path)
    result = _extract(brand, ALL)
    image = _kept(result, IMAGE["statement"])
    assert image.illustrative is True
    assert image.illustrative_reason == "image"
    assert image.strength == "soft"
    outside = _kept(result, OUTSIDE["statement"])
    assert outside.illustrative is False
    mixed = _kept(result, MIXED["statement"])
    assert mixed.illustrative is False


def test_D3_illustrative_questions_include_options_and_formats():
    _require(illustrative, "docla.brand.illustrative", "illustrative_questions")
    shown = _claim(
        "Crop photos to a square.",
        claim_id="c-shown",
        formats=["doc"],
        basis="shown",
        illustrative_value=True,
        reason="shown",
    )
    image = _claim("Use the pictured treatment.", claim_id="c-image", formats=[], illustrative_value=True, reason="image")
    stated = _claim("Use photos of real people.", claim_id="c-stated", formats=[])
    result = illustrative.illustrative_questions([shown, stated, image])
    assert [q.id for q in result] == ["claim.illustrative.c-shown", "claim.illustrative.c-image"]
    for question, statement, expected_format in zip(
        result, [shown.statement, image.statement], ["doc", None], strict=True
    ):
        assert question.kind == "illustrative"
        assert question.blocking is False
        assert question.source.file == FILE
        assert question.source.page == 1
        assert statement in question.text
        assert question.format == expected_format
        assert [(option.id, option.label, option.effects) for option in question.options] == [
            ("rule", "Make it a rule", []),
            ("example", "Only an example", []),
        ]
        assert question.recommended == "example"


def _git(brand, *args):
    return subprocess.run(["git", *args], cwd=brand, check=True, capture_output=True, text=True).stdout.strip()


def _commit(brand, message):
    subprocess.run(["git", "add", "-A"], cwd=brand, check=True)
    subprocess.run(
        ["git", "-c", "user.name=docla", "-c", "user.email=docla@localhost", "commit", "-m", message],
        cwd=brand,
        check=True,
        capture_output=True,
    )


def _main(args):
    try:
        return cli.main(args)
    except SystemExit as error:
        return error.code


def _by_statement(brand, statement):
    found = [q for q in questions.load_questions(brand) if q.id.startswith("claim.illustrative.") and statement in q.text]
    return found


def test_D4_cli_adds_and_drops_illustrative_questions(tmp_path, monkeypatch, capsys):
    _require(claims, "docla.brand.claims", "extract_claims")
    _require(agents, "docla.brand.agents", "brand_claude")
    _require(questions, "docla.brand.questions", "add_questions", "load_questions", "BrandQuestion", "QuestionSource")
    brand = _brand(tmp_path)
    font = questions.BrandQuestion(
        id="font.missing.acme-sans",
        kind="font",
        text="Supply the Acme Sans font files.",
        source=questions.QuestionSource(file="materials/fonts/fonts.yaml"),
    )
    questions.add_questions(brand, [font])
    _commit(brand, "Prepare materials")
    root = str(tmp_path / ".brand")

    def run(reply):
        claude, _ = _claude([reply])
        monkeypatch.setattr(agents, "brand_claude", lambda path: claude)
        return _main(["brand", "extract", "acme", "--root", root])

    assert run(ALL) == 0
    assert "2 illustrative claims" in capsys.readouterr().out
    assert _git(brand, "branch", "--show-current") == "main"
    assert _git(brand, "status", "--porcelain") == ""
    stored = questions.load_questions(brand)
    assert "font.missing.acme-sans" in [q.id for q in stored]
    shown = _by_statement(brand, SHOWN["statement"])
    image = _by_statement(brand, IMAGE["statement"])
    assert len(shown) == 1 and shown[0].answer is None
    assert len(image) == 1 and image[0].answer is None
    assert len([q for q in stored if q.id.startswith("claim.illustrative.")]) == 2

    assert run([STATED, IMAGE, OUTSIDE, MIXED]) == 0
    capsys.readouterr()
    stored = questions.load_questions(brand)
    ids = [q.id for q in stored]
    assert "font.missing.acme-sans" in ids
    assert shown[0].id not in ids
    assert [q.id for q in stored if q.id.startswith("claim.illustrative.") and q.answer is None] == [image[0].id]

    path = brand / "theme/ingest/questions.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    entry = next(q for q in data["questions"] if q["id"] == image[0].id)
    entry.update(answer="Only an example", answered_by="owner")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    _commit(brand, "Answer the image question")
    assert run([STATED, OUTSIDE, MIXED]) == 0
    kept = [q for q in questions.load_questions(brand) if q.id == image[0].id]
    assert len(kept) == 1
    assert kept[0].answer == "Only an example"


def test_D5_b07_judge_still_passes():
    judge = ROOT / "tests/judge/test_b_07_extract_claims.py"
    if judge.exists():
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(judge)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        code = result.returncode
    else:
        code = 0
    assert code == 0, "tests/judge/test_b_07_extract_claims.py must pass"
