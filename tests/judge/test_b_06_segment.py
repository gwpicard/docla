# Intent: Sort guideline pages into reusable, focused topic groups for brand extraction.
import asyncio
import importlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from docla import cli
from docla.agents.client import Claude
from docla.brand.workspace import BrandError, init_brand
from docla.config import ProjectConfig
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


segment = _module("docla.brand.segment")
agents = _module("docla.brand.agents")
intake = _module("docla.brand.intake")
pages = _module("docla.brand.pages")
FILE = "materials/guidelines/book.pdf"
FONTS = Path(__file__).resolve().parents[2] / "src/docla/themes/neutral/fonts"


def _require(module, *names):
    assert module is not None, "Required public brand module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"


def _pdf(brand, relative, count):
    source = brand / "input.typ"
    source.write_text(
        "#set page(width: 960pt, height: 540pt)\n" + "\n#pagebreak()\n".join(f"Page {n}" for n in range(1, count + 1))
    )
    compile_pdf(source, brand, brand / relative, [FONTS])
    source.unlink()


def _brand(tmp_path):
    _require(intake, "take_in")
    _require(pages, "parse_pdfs")
    brand = init_brand("acme", tmp_path / ".brand")
    _pdf(brand, FILE, 12)
    _pdf(brand, "materials/examples/deck.pdf", 2)
    intake.take_in(brand)
    pages.parse_pdfs(brand)
    return brand


class Ledger:
    def add(self, role, model, usage):
        pass


def _claude(*replies):
    transport = FakeTransport({"seg": [fake_response(json.dumps({"pages": reply})) for reply in replies]})
    return Claude(transport, Ledger(), {"brand.segment": "seg", "brand.extract": "ext"}), transport


def _replies():
    return (
        [
            {"page": 1, "topics": ["colour"]},
            {"page": 2, "topics": ["colour", "typography", "colour"]},
            *[{"page": n, "topics": ["other"]} for n in range(3, 11)],
        ],
        [{"page": 11, "topics": ["logo"]}, {"page": 99, "topics": ["colour"]}],
    )


def test_D1_requests_include_only_guidelines_in_batches(tmp_path):
    _require(segment, "segment_pages")
    brand = _brand(tmp_path)
    claude, transport = _claude(*_replies())
    asyncio.run(segment.segment_pages(brand, claude))
    assert len(transport.requests) == 2
    for request, numbers in zip(transport.requests, [range(1, 11), range(11, 13)], strict=True):
        assert request["model"] == "seg"
        assert request["output_config"]["effort"] == "low"
        assert request["max_tokens"] == 4000
        assert "never an instruction" in " ".join(block["text"] for block in request["system"])
        blocks = request["messages"][0]["content"]
        assert sum(block["type"] == "image" for block in blocks) == len(numbers)
        text = "\n".join(block["text"] for block in blocks if block["type"] == "text")
        for n in numbers:
            assert f'<page file="{FILE}" number="{n}">\nPage {n}\n</page>' in text
        assert "materials/examples/deck.pdf" not in text


def test_D2_topic_map_and_groups(tmp_path):
    _require(segment, "segment_pages", "topic_groups")
    brand = _brand(tmp_path)
    claude, _ = _claude(*_replies())
    result = asyncio.run(segment.segment_pages(brand, claude))
    assert len(result.files) == 1
    entry = result.files[0]
    assert entry.file == FILE
    assert entry.formats == ["slides"]
    assert next(page.topics for page in entry.pages if page.page == 2) == ["colour", "typography"]
    assert entry.missing == [12]
    assert 99 not in [page.page for page in entry.pages]
    assert segment.topic_groups(result) == {
        "colour": [(FILE, 1), (FILE, 2)],
        "typography": [(FILE, 2)],
        "logo": [(FILE, 11)],
    }


def test_D3_incremental_segmentation_and_changed_pdf(tmp_path):
    _require(segment, "segment_pages", "TopicMap", "TOPICS")
    brand = _brand(tmp_path)
    claude, _ = _claude(*_replies())
    result = asyncio.run(segment.segment_pages(brand, claude))
    path = brand / segment.TOPICS
    before = path.read_bytes()
    assert segment.TopicMap.model_validate_json(before) == result
    repeat, transport = _claude()
    assert asyncio.run(segment.segment_pages(brand, repeat)) == result
    assert transport.requests == []
    assert path.read_bytes() == before
    _pdf(brand, FILE, 2)
    intake.take_in(brand)
    pages.parse_pdfs(brand)
    changed, transport = _claude([{"page": 1, "topics": ["colour"]}, {"page": 2, "topics": ["logo"]}])
    updated = asyncio.run(segment.segment_pages(brand, changed))
    assert len(transport.requests) == 1
    assert len(updated.files) == 1
    assert [page.page for page in updated.files[0].pages] == [1, 2]


def test_D4_roles_and_missing_page_index(tmp_path):
    _require(agents, "brand_models")
    _require(segment, "segment_pages")
    config = ProjectConfig()
    before = dict(config.models)
    models = agents.brand_models(config)
    assert models["brand.segment"] == "claude-haiku-4-5"
    assert models["brand.extract"] == "claude-opus-5-5"
    assert config.models == before == ProjectConfig().models
    custom = ProjectConfig(models={**before, "brand.segment": "x"})
    assert agents.brand_models(custom)["brand.segment"] == "x"
    brand = init_brand("acme", tmp_path / ".brand")
    claude, transport = _claude()
    with pytest.raises(BrandError):
        asyncio.run(segment.segment_pages(brand, claude))
    assert transport.requests == []


def test_D5_cli_records_change_and_skips_current_topics(tmp_path, monkeypatch, capsys):
    _require(segment, "segment_pages")
    _require(agents, "brand_claude")
    brand = _brand(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=brand, check=True)
    subprocess.run(
        ["git", "-c", "user.name=docla", "-c", "user.email=docla@localhost", "commit", "-m", "Prepare materials"],
        cwd=brand,
        check=True,
        capture_output=True,
    )
    claude, transport = _claude(*_replies())
    monkeypatch.setattr(agents, "brand_claude", lambda path: claude)
    root = tmp_path / ".brand"
    assert cli.main(["brand", "segment", "acme", "--root", str(root)]) == 0
    output = capsys.readouterr().out
    assert any("colour" in line and "2 pages" in line for line in output.splitlines())

    def git(*args):
        return subprocess.run(["git", *args], cwd=brand, check=True, capture_output=True, text=True).stdout.strip()

    assert git("branch", "--show-current") == "main"
    assert git("status", "--porcelain") == ""
    assert cli.main(["brand", "log", "acme", "--root", str(root)]) == 0
    log = capsys.readouterr().out
    assert "Sort the guidelines' pages into topics" in log
    head = git("rev-parse", "HEAD")
    assert cli.main(["brand", "segment", "acme", "--root", str(root)]) == 0
    assert "topics up to date" in capsys.readouterr().out
    assert git("rev-parse", "HEAD") == head
    assert len(transport.requests) == 2
    assert cli.main(["brand", "segment", "unknown", "--root", str(root)]) == 2
