# Intent: Check rendered pages for blank content while preserving clean documents and exempt components.
import json
import runpy
from pathlib import Path

import pytest
import yaml
from PIL import Image

try:
    from docla import cli
    from docla.checks import catalogue, engine, source
    from docla.facts.layout import layout_facts
    from docla.facts.raster import PdfiumRasteriser
    from docla.render.compose import compose, font_paths
    from docla.source.parser import parse
    from docla.theme import neutral_theme
except ImportError as error:
    if error.name != "docla" and not str(error.name).startswith("docla."):
        raise
    import importlib.util

    if error.name and importlib.util.find_spec(error.name) is not None:
        raise
    cli = catalogue = engine = source = None

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
SEEDED = FIXTURES / "seeded-defects" / "pix.blank-page"


def run_cli(args, capsys):
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    try:
        code = cli.main(args)
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out.strip(), captured.err


def fixture(kind):
    path = SEEDED / kind / "doc.md"
    assert path.is_file(), f"seeded {kind} fixture must exist"
    return path


def test_D1_context_and_pixel_tier(tmp_path, capsys):
    assert engine is not None and hasattr(engine, "CheckContext") and hasattr(engine, "run_checks")
    assert catalogue is not None and hasattr(catalogue, "all_rules")
    path = fixture("fail")
    doc, parsed = parse(path.read_text())
    assert parsed == []
    context = engine.CheckContext(doc)
    assert hasattr(context, "pages_png") and hasattr(context, "page_png")
    assert context.pages_png == []
    other = engine.CheckContext(doc)
    context.pages_png.extend([tmp_path / "first.png", tmp_path / "second.png"])
    assert other.pages_png == []
    assert context.page_png(1) == tmp_path / "first.png"
    assert context.page_png(2) == tmp_path / "second.png"
    with pytest.raises(IndexError, match="3"):
        context.page_png(3)
    rules = [rule for rule in catalogue.all_rules() if rule.id == "pix.blank-page"]
    assert len(rules) == 1
    out = tmp_path / "build"
    code, _, err = run_cli(["build", str(path), "--out", str(out)], capsys)
    assert code == 0, err
    render = out / "render"
    facts = layout_facts(out / "doc.pdf", render / "main.typ", render, font_paths=font_paths(render))
    composition = compose(doc)
    images = PdfiumRasteriser().render(out / "doc.pdf", tmp_path / "images")
    assert len(images) == 1
    args = dict(facts=facts, composition=composition, theme=neutral_theme())
    assert engine.run_checks(rules, engine.CheckContext(doc, **args)) == []
    findings = engine.run_checks(rules, engine.CheckContext(doc, pages_png=images, **args))
    assert len(findings) == 1
    finding = findings[0]
    assert (finding.rule_id, finding.section_id, finding.page) == ("pix.blank-page", "blank1", 1)
    assert finding.region.model_dump() == {"x": 0, "y": 0, "w": 960, "h": 540}
    assert finding.measured["coverage"] < finding.measured["min"] == 0.001


def test_D2_catalogue_rule_metadata_and_order():
    assert catalogue is not None and source is not None
    rules = catalogue.all_rules()
    ids = [rule.id for rule in rules]
    assert ids.count("pix.blank-page") == 1
    index = ids.index("pix.blank-page")
    assert all(ids.index(rule.id) < index for rule in [*catalogue.m1_rules(), *source.M2_RULES])
    rule = rules[index]
    assert (rule.title, rule.origin, rule.tier, rule.severity, rule.strength, rule.status) == (
        "Pages are not blank",
        "manual",
        "pixel",
        "error",
        "hard",
        "active",
    )
    assert rule.remedy.class_ == "restructure" and rule.remedy.hint.strip()
    assert rule.check == {"kind": "ink-coverage", "min": 0.001, "skip_components": ["chapter-break", "cover"]}
    assert rule.provenance.source == {"doc": "DESIGN.md", "section": "10.5"}
    assert rule.scope.format is None


def test_D3_check_seeded_failure_and_pass(tmp_path, capsys):
    out = tmp_path / "fail"
    code, output, _ = run_cli(["check", str(fixture("fail")), "--out", str(out)], capsys)
    assert code == 1
    assert len(output.splitlines()) == 1 and output.startswith("error pix.blank-page blank1 ")
    findings = json.loads((out / "doc.findings.json").read_text())
    assert len(findings) == 1
    assert (findings[0]["rule_id"], findings[0]["section_id"], findings[0]["page"]) == ("pix.blank-page", "blank1", 1)
    assert findings[0]["measured"]["coverage"] < findings[0]["measured"]["min"] == 0.001
    code, output, _ = run_cli(["check", str(fixture("pass")), "--out", str(tmp_path / "pass")], capsys)
    assert (code, output) == (0, "no findings")


@pytest.mark.parametrize("component", ["chapter-break", "cover"])
def test_D4_exempt_components(component, tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text(
        "---\ndoctype: pitch-deck\nformat: slides\ntitle: Test\n---\n\n"
        f'::: {{#blank1 .section intent="{component}"}}\n## a\n:::\n'
    )
    code, output, _ = run_cli(["check", str(path), "--out", str(tmp_path / "out")], capsys)
    assert (code, output) == (0, "no findings")


def test_D4_check_rasterises_but_build_does_not(tmp_path, capsys):
    path = fixture("pass")
    check_out = tmp_path / "check"
    code, output, _ = run_cli(["check", str(path), "--out", str(check_out)], capsys)
    assert (code, output) == (0, "no findings")
    image = check_out / "pages" / "p01.png"
    assert image.is_file()
    with Image.open(image) as page:
        assert page.size == (1920, 1080)
    build_out = tmp_path / "build"
    code, _, err = run_cli(["build", str(path), "--out", str(build_out)], capsys)
    assert code == 0, err
    assert (build_out / "doc.pdf").is_file()
    assert not (build_out / "pages").exists()


def test_D5_existing_clean_texts(tmp_path, capsys):
    for judge in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        texts = runpy.run_path(str(ROOT / "tests" / "judge" / judge))
        for name in ("SLIDES", "DOC"):
            path = tmp_path / f"{judge}-{name}.md"
            path.write_text(texts[name])
            code, output, _ = run_cli(["check", str(path), "--out", str(tmp_path / f"out-{judge}-{name}")], capsys)
            assert (code, output) == (0, "no findings"), (judge, name, output)


@pytest.mark.parametrize("component", ["statement", "closing", "contact", "quote", "agenda", "body", "callout"])
def test_D5_component_fixtures_are_clean(component, tmp_path, capsys):
    data = yaml.safe_load((FIXTURES / "components" / f"{component}.yaml").read_text())
    doc = component in ("body", "callout")
    text = (
        f"---\ndoctype: {'report' if doc else 'pitch-deck'}\nformat: {'doc' if doc else 'slides'}\ntitle: Test\n---\n\n"
        f'::: {{#{data["id"]} .section intent="{data["intent"]}"}}\n'
    )
    if data.get("title"):
        text += f"## {data['title']}\n\n"
    for paragraph in data.get("paragraphs", []):
        text += f"{paragraph}\n\n"
    for item in data.get("items", []):
        head = item.get("head")
        text += f"- {head + ': ' if head else ''}{item['body']}\n"
    if data.get("source_line"):
        text += f"\n> source: {data['source_line']}\n"
    text += ":::\n"
    path = tmp_path / "doc.md"
    path.write_text(text)
    code, output, _ = run_cli(["check", str(path), "--out", str(tmp_path / "out")], capsys)
    assert (code, output) == (0, "no findings"), output
