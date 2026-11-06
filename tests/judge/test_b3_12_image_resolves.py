# Intent: Report unresolved section images while preserving existing check and build behaviour.
import dataclasses
import importlib
import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path

from PIL import Image

from docla.model import Document, Section


def _subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name or importlib.util.find_spec(name) is not None:
            raise
        return None


catalogue = _subject("docla.checks.catalogue")
assets = _subject("docla.checks.assets")
engine = _subject("docla.checks.engine")
source = _subject("docla.checks.source")
cli = _subject("docla.cli")
parser = _subject("docla.source.parser")

ROOT = Path(__file__).resolve().parents[2]
SEEDED = ROOT / "tests/fixtures/seeded-defects"
FIXTURE = SEEDED / "source.image-resolves"


def _run(argv, capsys):
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    try:
        code = cli.main(argv)
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr()
    return code, output.out, output.err


def test_D1_catalogue_and_context_contract():
    assert catalogue is not None and hasattr(catalogue, "all_rules") and hasattr(catalogue, "m1_rules")
    assert source is not None and hasattr(source, "RULES") and hasattr(source, "M2_RULES")
    assert engine is not None and hasattr(engine, "CheckContext")
    first_six = [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
    ]
    assert [rule.id for rule in catalogue.m1_rules()] == first_six
    assert len(source.RULES) == 2
    rules = catalogue.all_rules()
    ids = [rule.id for rule in rules]
    assert ids[:7] == first_six + ["source.intent-known"]
    assert ids.count("source.image-resolves") == 1
    index = ids.index("source.image-resolves")
    assert all(ids.index(rule.id) < index for rule in [*catalogue.m1_rules(), *source.M2_RULES])
    rule = rules[index]
    assert (rule.severity, rule.tier, rule.remedy.class_) == ("warning", "source", "ask")
    fields = {field.name: field for field in dataclasses.fields(engine.CheckContext)}
    assert "assets" in fields and fields["assets"].default is None


def test_D2_image_resolution_and_final_severity(tmp_path):
    assert assets is not None and hasattr(assets, "RULES"), "docla.checks.assets.RULES must exist"
    assert engine is not None and hasattr(engine, "run_checks") and hasattr(engine, "CheckContext")
    assert "assets" in {field.name for field in dataclasses.fields(engine.CheckContext)}
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    doc = Document(front={}, format="slides", sections=[Section(id="image1", intent="full-image", image="missing.png")])
    findings = engine.run_checks(assets.RULES, engine.CheckContext(doc, assets=[first, second]))
    assert len(findings) == 1
    finding = findings[0]
    assert (finding.rule_id, finding.severity, finding.section_id) == ("source.image-resolves", "warning", "image1")
    assert finding.measured == {"image": "missing.png"}
    assert "missing.png" in finding.message and str(first) in finding.message and str(second) in finding.message
    final = engine.run_checks(assets.RULES, engine.CheckContext(doc, assets=[first, second], final=True))
    assert len(final) == 1 and final[0].severity == "error"
    assert engine.run_checks(assets.RULES, engine.CheckContext(doc)) == []
    no_image = Document(front={}, format="slides", sections=[Section(id="image1", intent="full-image")])
    assert engine.run_checks(assets.RULES, engine.CheckContext(no_image, assets=[first, second])) == []
    (second / "missing.png").write_bytes(b"file")
    assert engine.run_checks(assets.RULES, engine.CheckContext(doc, assets=[first, second])) == []


def test_D3_missing_fixture_check_and_build(tmp_path, capsys):
    path = FIXTURE / "fail/doc.md"
    assert path.is_file()
    assert parser is not None and hasattr(parser, "parse")
    doc, _ = parser.parse(path.read_text())
    assert len(doc.sections) == 1 and doc.sections[0].id
    section_id = doc.sections[0].id
    for extra, severity, expected in (([], "warning", 0), (["--final"], "error", 1)):
        code, out, _ = _run(["check", str(path), "--out", str(tmp_path / severity), *extra], capsys)
        assert code == expected, out
        assert any(
            line.startswith(f"{severity} source.image-resolves {section_id} ") and "missing.png" in line
            for line in out.splitlines()
        ), out
    code, _, err = _run(["build", str(path), "--out", str(tmp_path / "build")], capsys)
    assert code == 2 and "missing.png" in err


def test_D4_generated_image_and_pass_fixture(tmp_path, capsys):
    picture = FIXTURE / "pass/assets/picture.png"
    licence = FIXTURE / "pass/assets/LICENCE.txt"
    script = ROOT / "scripts/make_fixture_images.py"
    assert picture.is_file() and licence.is_file() and script.is_file()
    text = licence.read_text().lower()
    assert all(value in text for value in ("picture.png", "own work", "scripts/make_fixture_images.py"))
    with Image.open(picture) as image:
        assert image.format == "PNG" and image.size == (2000, 1125)
        expected = image.convert("RGB").tobytes()
    result = subprocess.run([sys.executable, str(script), str(tmp_path / "generated")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with Image.open(tmp_path / "generated/picture.png") as generated:
        assert generated.format == "PNG" and generated.size == (2000, 1125)
        assert generated.convert("RGB").tobytes() == expected
    code, out, _ = _run(["check", str(FIXTURE / "pass/doc.md"), "--out", str(tmp_path / "out")], capsys)
    assert code == 0 and "source.image-resolves" not in out


def test_D5_existing_clean_documents_and_geometry_failure(tmp_path, capsys):
    for judge in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(ROOT / "tests/judge" / judge))
        for name in ("SLIDES", "DOC"):
            path = tmp_path / f"{judge}-{name}.md"
            path.write_text(examples[name])
            code, out, _ = _run(["check", str(path), "--out", str(tmp_path / (judge + name))], capsys)
            assert code == 0 and out.splitlines() == ["no findings"], (judge, name, out)
    code, out, _ = _run(["check", str(SEEDED / "geo.text-fits/fail/doc.md"), "--out", str(tmp_path / "geo")], capsys)
    assert code == 1 and any(line.startswith("error geo.text-fits ") for line in out.splitlines()), out
