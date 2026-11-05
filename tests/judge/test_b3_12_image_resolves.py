# Intent: report unresolved section images at the source tier while preserving existing check and build behaviour.
import dataclasses
import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path

from PIL import Image

from docla import cli
from docla.checks import catalogue, engine, source
from docla.model import Document, Section

try:
    import docla.checks.assets as assets
except ImportError as error:
    if error.name != "docla.checks.assets" or importlib.util.find_spec("docla.checks.assets") is not None:
        raise
    assets = None

ROOT = Path(__file__).resolve().parents[2]
SEEDED = ROOT / "tests" / "fixtures" / "seeded-defects"
FIXTURE = SEEDED / "source.image-resolves"


def _run(argv, capsys):
    assert hasattr(cli, "main"), "docla.cli.main must exist"
    try:
        code = cli.main(argv)
    except SystemExit as exit_:
        code = exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_catalogue_and_context():
    expected = [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
        "source.intent-known",
    ]
    rules = catalogue.all_rules()
    ids = [rule.id for rule in rules]
    assert ids[:7] == expected
    assert [rule.id for rule in catalogue.m1_rules()] == expected[:6]
    assert len(source.RULES) == 2
    assert ids.count("source.image-resolves") == 1
    rule = rules[ids.index("source.image-resolves")]
    assert (rule.severity, rule.tier, rule.remedy.class_) == ("error", "source", "ask")
    assert all(
        ids.index(rule.id) < ids.index("source.image-resolves") for rule in catalogue.m1_rules() + source.M2_RULES
    )
    fields = {field.name: field for field in dataclasses.fields(engine.CheckContext)}
    assert "assets" in fields and fields["assets"].default is None


def test_D2_image_resolution(tmp_path):
    assert assets is not None and hasattr(assets, "RULES"), "docla.checks.assets.RULES must exist"
    assert "assets" in {field.name for field in dataclasses.fields(engine.CheckContext)}
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    doc = Document(front={}, format="slides", sections=[Section(id="image1", intent="full-image", image="missing.png")])

    def check(document, folders):
        return engine.run_checks(assets.RULES, engine.CheckContext(document, assets=folders))

    findings = check(doc, [first, second])
    assert len(findings) == 1
    finding = findings[0]
    assert (finding.rule_id, finding.severity, finding.section_id) == ("source.image-resolves", "error", "image1")
    assert finding.measured == {"image": "missing.png"}
    assert "missing.png" in finding.message
    assert str(first) in finding.message and str(second) in finding.message
    (second / "missing.png").write_bytes(b"image contents")
    assert check(doc, [first, second]) == []
    assert engine.run_checks(assets.RULES, engine.CheckContext(doc)) == []
    no_image = Document(front={}, format="slides", sections=[Section(id="image1", intent="full-image")])
    assert check(no_image, [first, second]) == []


def test_D3_missing_image_check_and_build(tmp_path, capsys):
    fixture = FIXTURE / "fail" / "doc.md"
    assert fixture.is_file(), "missing-image fail fixture must exist"
    # Read the section id from the public parser's result.
    from docla.source.parser import parse

    doc, _ = parse(fixture.read_text())
    section_id = doc.sections[0].id
    code, out, _ = _run(["check", str(fixture), "--out", str(tmp_path / "check")], capsys)
    assert code == 1
    assert any(
        line.startswith(f"error source.image-resolves {section_id} ") and "missing.png" in line
        for line in out.splitlines()
    )
    code, _, err = _run(["build", str(fixture), "--out", str(tmp_path / "build")], capsys)
    assert code == 2
    assert "missing.png" in err


def test_D3_missing_image_reproduces_source_fallback(tmp_path, capsys):
    fixture = tmp_path / "doc.md"
    fixture.write_text(
        "---\ndoctype: pitch-deck\nformat: slides\n---\n\n"
        '::: {#image1 .section intent="full-image" image="missing.png"}\nA quiet scene.\n:::\n'
    )
    code, out, _ = _run(["check", str(fixture), "--out", str(tmp_path / "out")], capsys)
    assert code == 1
    assert any(
        line.startswith("error source.image-resolves image1 ") and "missing.png" in line for line in out.splitlines()
    )


def test_D4_fixture_image_and_generator(tmp_path, capsys):
    picture = FIXTURE / "pass" / "assets" / "picture.png"
    licence = picture.with_name("LICENCE.txt")
    script = ROOT / "scripts" / "make_fixture_images.py"
    assert picture.is_file() and licence.is_file() and script.is_file()
    note = licence.read_text()
    assert all(text in note for text in ("picture.png", "own work", "scripts/make_fixture_images.py"))
    with Image.open(picture) as original:
        assert original.format == "PNG" and original.size == (2000, 1125)
        result = subprocess.run(
            [sys.executable, str(script), str(tmp_path / "generated")], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        generated = tmp_path / "generated" / "picture.png"
        assert generated.is_file()
        with Image.open(generated) as copy:
            assert copy.format == "PNG" and copy.size == (2000, 1125)
            assert copy.convert("RGB").tobytes() == original.convert("RGB").tobytes()
    code, out, _ = _run(["check", str(FIXTURE / "pass" / "doc.md"), "--out", str(tmp_path / "out")], capsys)
    assert code == 0, out
    assert not any("source.image-resolves" in line for line in out.splitlines())


def test_D5_existing_clean_documents_and_text_fits(tmp_path, capsys):
    for filename in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(ROOT / "tests" / "judge" / filename))
        for kind in ("SLIDES", "DOC"):
            path = tmp_path / (filename + kind + ".md")
            path.write_text(examples[kind])
            code, out, _ = _run(["check", str(path), "--out", str(tmp_path / "out")], capsys)
            assert (code, out.splitlines()) == (0, ["no findings"]), (filename, kind, out)
    fixture = SEEDED / "geo.text-fits" / "fail" / "doc.md"
    code, out, _ = _run(["check", str(fixture), "--out", str(tmp_path / "out")], capsys)
    assert code == 1
    assert any(line.startswith("error geo.text-fits ") for line in out.splitlines())
