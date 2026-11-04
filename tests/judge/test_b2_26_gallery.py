# Intent: show every slide component in a single checked and buildable gallery deck.
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pdfplumber

try:
    from docla import cli
    from docla.render import components, compose
    from docla.source import parser
except ImportError as error:
    if error.name not in {
        "docla", "docla.cli", "docla.render", "docla.render.components",
        "docla.render.compose", "docla.source", "docla.source.parser",
    }:
        raise
    cli = components = compose = parser = None

ROOT = Path(__file__).resolve().parents[2]
GALLERY = ROOT / "tests/fixtures/slides/gallery.md"
SCRIPT = ROOT / "scripts/build_gallery.py"


def _gallery():
    assert GALLERY.is_file(), "tests/fixtures/slides/gallery.md must exist"
    assert parser is not None and hasattr(parser, "parse"), "docla.source.parser.parse must exist"
    return parser.parse(GALLERY.read_text(encoding="utf-8"))


def _build_copy(tmp_path):
    assert GALLERY.is_file(), "tests/fixtures/slides/gallery.md must exist"
    assert SCRIPT.is_file(), "scripts/build_gallery.py must exist"
    slides = tmp_path / "tests/fixtures/slides"
    slides.mkdir(parents=True)
    shutil.copy2(GALLERY, slides / "gallery.md")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(SCRIPT, scripts / SCRIPT.name)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "src"), env.get("PYTHONPATH", "")]))
    result = subprocess.run(
        [sys.executable, str(scripts / SCRIPT.name)], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return slides / "gallery.md", tmp_path / "build" / "gallery.pdf"


def test_D1_gallery_parses_and_has_cover_and_closing():
    doc, findings = _gallery()
    assert findings == []
    assert doc.format == "slides"
    assert doc.sections
    assert doc.sections[0].intent == "cover"
    assert doc.sections[-1].intent == "closing"


def test_D2_gallery_composes_every_slide_manifest():
    doc, findings = _gallery()
    assert findings == []
    assert components is not None and hasattr(components, "all_manifests"), "all_manifests must exist"
    assert compose is not None and hasattr(compose, "compose"), "compose must exist"
    manifests = components.all_manifests()
    expected = {manifest.name for manifest in manifests.values() if manifest.format == "slides"}
    assert expected
    chosen = {section.component for section in compose.compose(doc).sections}
    assert expected <= chosen, f"Gallery does not use: {sorted(expected - chosen)}"


def test_D3_gallery_check_has_no_errors(tmp_path, capsys):
    gallery, _ = _build_copy(tmp_path)
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    out = tmp_path / "check"
    code = cli.main(["check", str(gallery), "--out", str(out)])
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
    report = out / "gallery.findings.json"
    assert report.is_file(), captured.out + captured.err
    findings = json.loads(report.read_text(encoding="utf-8"))
    assert [finding for finding in findings if finding["severity"] == "error"] == []


def test_D4_builder_produces_one_pdf_page_per_section(tmp_path):
    doc, findings = _gallery()
    assert findings == []
    _, pdf = _build_copy(tmp_path)
    assert pdf.is_file(), "builder must write build/gallery.pdf"
    with pdfplumber.open(pdf) as deck:
        assert len(deck.pages) == len(doc.sections)
