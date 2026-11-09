# Intent: Look over a rendered document, cache its facts and report deterministic and semantic coverage.
import asyncio
import hashlib
import importlib
import importlib.util
import runpy
from pathlib import Path

from docla import cli
from docla.model import Finding
from docla.render.compose import assemble, compose, font_paths
from docla.render.typst import compile_pdf
from docla.source.parser import parse
from docla.theme import neutral_theme

SUBJECT = "docla.loop.look"
try:
    if importlib.util.find_spec(SUBJECT) is None:
        look_module = None
    else:
        look_module = importlib.import_module(SUBJECT)
except ImportError as error:
    if error.name != SUBJECT and not str(error.name).startswith(SUBJECT + "."):
        raise
    look_module = None

JUDGE = Path(__file__).parent
FIXTURE = JUDGE.parent / "fixtures/seeded-defects/geo.text-fits/fail/doc.md"


def _interface():
    assert look_module is not None, "docla.loop.look must exist"
    for name in ("look", "LookContext", "Look", "CriticPage"):
        assert hasattr(look_module, name), f"docla.loop.look.{name} must exist"
    return look_module


def _build(tmp_path, text):
    doc, parsed = parse(text)
    assert parsed == []
    theme = neutral_theme()
    comp = compose(doc)
    main = assemble(comp, tmp_path / "render", theme=theme)
    pdf = tmp_path / "deck.pdf"
    compile_pdf(main, main.parent, pdf, font_paths(main.parent))
    return doc, theme, comp, main, pdf


def _context(tmp_path, built, **kwargs):
    module = _interface()
    doc, theme, _, main, _ = built
    return module.LookContext(doc=doc, theme=theme, main=main, project=tmp_path, workdir=tmp_path / "work", **kwargs)


def _overflow():
    return FIXTURE.read_text() + '\n::: {#clean2 .section intent="statement"}\n## One pilot is enough\n:::\n'


def _clean_slides():
    return runpy.run_path(str(JUDGE / "test_m1_17_cli_build_check.py"))["SLIDES"]


def _warning():
    return Finding(
        id="semantic-1",
        rule_id="semantic.test",
        tier="semantic",
        severity="warning",
        format="slides",
        section_id="clean2",
        message="Needs attention",
        fingerprint="semantic-1",
        remedy={"class": "report", "hint": "Review"},
    )


def test_D1_blocked_page_and_critic_inputs(tmp_path):
    module = _interface()
    built = _build(tmp_path, _overflow())
    calls = []

    async def critic(page):
        calls.append(page)
        return []

    result = asyncio.run(module.look(built[4], built[2], _context(tmp_path, built, critic=critic)))
    assert isinstance(result, module.Look)
    assert any(
        f.rule_id == "geo.text-fits" and f.severity == "error" and f.section_id == "c4e10" for f in result.findings
    )
    assert result.critic_pages == [2]
    assert len(calls) == 1 and isinstance(calls[0], module.CriticPage)
    assert calls[0].page == 2 and calls[0].width == 960
    assert calls[0].regions
    assert all(region.page == 2 and region.section_id == "clean2" for region in calls[0].regions)


def test_D2_critic_findings_and_clean_page_hash_skip(tmp_path):
    module = _interface()
    built = _build(tmp_path, _overflow())
    calls = []
    warning = _warning()

    async def warned(page):
        calls.append(page.page)
        return [warning]

    result = asyncio.run(module.look(built[4], built[2], _context(tmp_path, built, critic=warned)))
    assert calls == [2]
    assert warning in result.findings
    assert result.page_hashes[2] not in result.clean_pages
    calls.clear()

    async def clean(page):
        calls.append(page.page)
        return []

    clean_result = asyncio.run(module.look(built[4], built[2], _context(tmp_path, built, critic=clean)))
    assert calls == [2]
    page_hash = hashlib.sha256(clean_result.pngs[1].read_bytes()).hexdigest()
    assert clean_result.page_hashes[2] == page_hash
    assert page_hash in clean_result.clean_pages
    calls.clear()
    again = asyncio.run(
        module.look(built[4], built[2], _context(tmp_path, built, critic=clean, clean_pages=frozenset({page_hash})))
    )
    assert calls == []
    assert again.critic_pages == []
    assert again.tiers["semantic"] == "skipped"


def test_D3_facts_are_cached_by_pdf_hash(tmp_path, monkeypatch):
    module = _interface()
    built = _build(tmp_path, _clean_slides())
    result = asyncio.run(module.look(built[4], built[2], _context(tmp_path, built)))
    digest = hashlib.sha256(built[4].read_bytes()).hexdigest()
    assert result.pdf_sha256 == digest
    assert (tmp_path / ".docla/cache/facts" / (digest + ".json")).is_file()

    def fail(*args, **kwargs):
        raise AssertionError("layout facts must come from the cache")

    monkeypatch.setattr(module, "layout_facts", fail)
    again = asyncio.run(module.look(built[4], built[2], _context(tmp_path, built)))
    assert again.facts == result.facts


def test_D4_draft_record_and_critic_failure(tmp_path):
    module = _interface()
    built = _build(tmp_path, _clean_slides())
    result = asyncio.run(module.look(built[4], built[2], _context(tmp_path, built, final=False)))
    assert result.findings == []
    assert result.could_not == []
    assert result.tiers == {"source": "ok", "geometry": "ok", "pixel": "ok", "semantic": "skipped"}
    record = result.record()
    from docla.store import LookRecord

    assert isinstance(record, LookRecord)
    assert (record.pages, record.method, record.clean) == (2, "marks", True)
    assert record.could_not == [] and record.tiers == result.tiers

    async def critic(page):
        if page.page == 2:
            raise RuntimeError("critic unavailable")
        return []

    failed = asyncio.run(module.look(built[4], built[2], _context(tmp_path, built, critic=critic)))
    assert failed.critic_pages == [1, 2]
    assert failed.tiers["semantic"] == "failed"
    assert any(entry.startswith("semantic page 2") and "critic unavailable" in entry for entry in failed.could_not)
    assert failed.record().clean is False


def test_D5_clean_check_output_stays_exact(tmp_path, capsys):
    for filename in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(JUDGE / filename))
        for kind in ("SLIDES", "DOC"):
            source = tmp_path / (filename + kind + ".md")
            source.write_text(examples[kind])
            code = cli.main(["check", str(source), "--out", str(tmp_path / (filename + kind))])
            output = capsys.readouterr()
            assert code == 0
            assert output.out == "no findings\n"
