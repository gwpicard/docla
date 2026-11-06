# Intent: final checks enforce minimum image resolution and draft checks remain clean.
import importlib
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image

def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name:
            raise
        return None


cli = _optional("docla.cli")
theme = _optional("docla.theme")
catalogue = _optional("docla.checks.catalogue")
engine = _optional("docla.checks.engine")
source = _optional("docla.checks.source")
swatch = _optional("docla.render.swatch")
from docla.model import Document, Section
from docla.source import parse, serialise

ROOT = Path(__file__).resolve().parents[2]
SEEDED = ROOT / "tests/fixtures/seeded-defects/geo.image-dpi"


def _rule():
    assert catalogue is not None and hasattr(catalogue, "all_rules")
    rules = [r for r in catalogue.all_rules() if r.id == "geo.image-dpi"]
    assert len(rules) == 1, "exactly one geo.image-dpi rule must exist"
    return rules[0]


def _run(path, out, capsys, final=False):
    assert cli is not None and hasattr(cli, "main")
    args = ["check", str(path), "--out", str(out)]
    if final:
        args.append("--final")
    try:
        code = cli.main(args)
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _fixture(kind):
    path = SEEDED / kind / "doc.md"
    assert path.is_file(), f"missing working file: {path}"
    return path


def _facts(tmp_path):
    assert swatch is not None and hasattr(swatch, "swatch")
    assert theme is not None and hasattr(theme, "neutral_theme")
    path = _fixture("fail")
    doc, findings = parse(path.read_text())
    assert findings == []
    assert len(doc.sections) == 1
    result = swatch.swatch(doc, doc.sections[0].id, tmp_path, theme.neutral_theme(), assets=[path.parent / "assets"])
    assert hasattr(result.facts, "images"), "layout facts must expose images"
    assert len(result.facts.images) == 1
    return doc, result.facts


def test_D1_neutral_and_missing_imagery(tmp_path):
    assert theme is not None and hasattr(theme, "neutral_theme") and hasattr(theme, "load_theme")
    neutral = theme.neutral_theme()
    assert hasattr(neutral.tokens, "imagery"), "tokens.imagery must exist"
    assert neutral.tokens.imagery is not None
    assert neutral.tokens.imagery.min_dpi == 150
    copied = tmp_path / "theme"
    shutil.copytree(theme.NEUTRAL_ROOT, copied)
    tokens = copied / "tokens.yaml"
    data = yaml.safe_load(tokens.read_text())
    del data["imagery"]
    tokens.write_text(yaml.safe_dump(data))
    assert theme.load_theme(copied).tokens.imagery is None


def test_D2_catalogue_metadata_and_order():
    rule = _rule()
    assert (rule.title, rule.origin, rule.strength, rule.status) == (
        "Images have at least the theme's minimum resolution",
        "manual",
        "hard",
        "active",
    )
    assert (rule.tier, rule.severity, rule.remedy.class_) == ("geometry", "error", "restructure")
    assert rule.check == {"kind": "image-dpi", "min": 150}
    assert rule.provenance.source == {"doc": "DESIGN.md", "section": "10.5"}
    assert [r.id for r in source.RULES] == ["source.citations-resolve", "source.empty-section"]
    assert [r.id for r in catalogue.m1_rules()] == [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
    ]
    prefix = [*catalogue.m1_rules(), *source.M2_RULES]
    assert catalogue.all_rules()[: len(prefix)] == prefix
    assert catalogue.all_rules().index(rule) >= len(prefix)


def test_D3_final_fail_fixture_and_rendered_finding(tmp_path, capsys):
    rule = _rule()
    path = _fixture("fail")
    image_path = path.parent / "assets/small.png"
    assert image_path.is_file()
    with Image.open(image_path) as image:
        assert image.size == (60, 34)
    code, out, err = _run(path, tmp_path / "check", capsys, final=True)
    assert code == 1, (out, err)
    assert any(line.startswith("error geo.image-dpi ") for line in out.splitlines()), out
    doc, facts = _facts(tmp_path)
    assert "final" in engine.CheckContext.__dataclass_fields__, "CheckContext.final must exist"
    hits = engine.run_checks([rule], engine.CheckContext(doc=doc, facts=facts, theme=theme.neutral_theme(), final=True))
    assert len(hits) == 1
    hit = hits[0]
    image = facts.images[0]
    assert hit.rule_id == "geo.image-dpi"
    assert hit.measured == {"dpi": round(min(image.dpi_x, image.dpi_y), 1), "min": 150}
    assert hit.measured["dpi"] < 150
    assert hit.section_id == image.section_id
    assert hit.page == image.box.page
    assert "150" in hit.message


def test_D4_final_pass_and_generated_assets(tmp_path, capsys):
    path = _fixture("pass")
    code, out, err = _run(path, tmp_path / "check", capsys, final=True)
    assert code == 0, (out, err)
    assert not any("geo.image-dpi" in line for line in out.splitlines())
    for kind, name, size in (("fail", "small.png", (60, 34)), ("pass", "picture.png", (2000, 1125))):
        folder = SEEDED / kind / "assets"
        assert (folder / name).is_file()
        with Image.open(folder / name) as image:
            assert image.size == size
        licence = folder / "LICENCE.txt"
        assert licence.is_file()
        text = licence.read_text().lower()
        assert name in text and "own work" in text and "scripts/make_fixture_images.py" in text
    script = ROOT / "scripts/make_fixture_images.py"
    assert script.is_file(), "fixture image generator must exist"
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path), "--name", "small.png", "--size", "60x34"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    with Image.open(tmp_path / "small.png") as generated, Image.open(SEEDED / "fail/assets/small.png") as committed:
        assert generated.size == committed.size == (60, 34)
        assert generated.convert("RGB").tobytes() == committed.convert("RGB").tobytes()


def test_D5_draft_is_silent_for_low_resolution(tmp_path, capsys):
    rule = _rule()
    path = _fixture("fail")
    code, out, err = _run(path, tmp_path / "check", capsys)
    assert code == 0, (out, err)
    assert not any("geo.image-dpi" in line for line in out.splitlines())
    doc, facts = _facts(tmp_path)
    assert "final" in engine.CheckContext.__dataclass_fields__, "CheckContext.final must exist"
    hits = engine.run_checks(
        [rule], engine.CheckContext(doc=doc, facts=facts, theme=theme.neutral_theme(), final=False)
    )
    assert hits == []


def test_D6_clean_existing_examples_and_low_resolution_image(tmp_path, capsys):
    for judge in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(ROOT / "tests/judge" / judge))
        for name in ("SLIDES", "DOC"):
            path = tmp_path / f"{judge}-{name}.md"
            path.write_text(examples[name])
            code, out, err = _run(path, tmp_path / f"out-{judge}-{name}", capsys)
            assert code == 0, (out, err)
            assert out.splitlines() == ["no findings"]
    section = Section.model_validate(
        yaml.safe_load((ROOT / "tests/fixtures/components/image-with-text.yaml").read_text())
    )
    assets = tmp_path / "assets"
    assets.mkdir()
    Image.new("RGB", (320, 240), (40, 100, 160)).save(assets / section.image)
    doc = Document(front={"doctype": "pitch-deck", "title": "Deck"}, format="slides", sections=[section])
    path = tmp_path / "image.md"
    path.write_text(serialise(doc))
    code, out, err = _run(path, tmp_path / "out-image", capsys)
    assert code == 0, (out, err)
    assert out.splitlines() == ["no findings"]
