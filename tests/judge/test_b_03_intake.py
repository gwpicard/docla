# Intent: record every brand material deterministically and commit intake as a brand change.
import hashlib
import importlib
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

from docla.render.typst import compile_pdf


def _import_subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if not error.name or not (name == error.name or name.startswith(error.name + ".")):
            raise
        try:
            spec = importlib.util.find_spec(error.name)
        except ModuleNotFoundError as missing:
            if not missing.name or not error.name.startswith(missing.name + "."):
                raise
            spec = None
        if spec is not None:
            raise
        return None


intake = _import_subject("docla.brand.intake")
workspace = _import_subject("docla.brand.workspace")
changes = _import_subject("docla.brand.changes")
cli = _import_subject("docla.cli")
FONTS = Path(__file__).resolve().parents[2] / "src/docla/themes/neutral/fonts"


def _brand(root):
    assert workspace is not None and hasattr(workspace, "init_brand"), "init_brand must exist"
    workspace.init_brand("acme", root)
    return root / "acme"


def _pdf(path, width, height, pages, text="Material"):
    source = path.parent / "source.typ"
    source.write_text(
        f"#set page(width: {width}pt, height: {height}pt)\n"
        + "\n#pagebreak()\n".join([text] * pages)
        + "\n"
    )
    compile_pdf(source, path.parent, path, font_paths=[FONTS])
    source.unlink()


def _materials(brand):
    materials = brand / "materials"
    for folder in ("guidelines", "examples", "templates", "logos", "notes", "fonts"):
        (materials / folder).mkdir(parents=True, exist_ok=True)
    _pdf(materials / "guidelines/book.pdf", 960, 540, 3)
    _pdf(materials / "examples/report.pdf", 595, 842, 2)
    with ZipFile(materials / "templates/deck.pptx", "w") as archive:
        for name in ("[Content_Types].xml", "ppt/slides/slide1.xml", "ppt/slides/slide2.xml"):
            archive.writestr(name, "<root/>")
    with ZipFile(materials / "templates/memo.dotx", "w") as archive:
        archive.writestr("docProps/app.xml", "<Properties><Pages>4</Pages></Properties>")
    (materials / "logos/logo.svg").write_text("<svg/>")
    (materials / "notes/notes.md").write_text("Brand notes\n")
    shutil.copyfile(FONTS / "Inter-Regular.ttf", materials / "fonts/Inter-Regular.ttf")


def _require_intake():
    assert intake is not None and hasattr(intake, "take_in"), "docla.brand.intake.take_in must exist"
    assert hasattr(intake, "Manifest"), "docla.brand.intake.Manifest must exist"
    assert hasattr(intake, "MaterialEntry"), "docla.brand.intake.MaterialEntry must exist"


def test_D1_manifest_lists_materials_with_metadata(tmp_path):
    _require_intake()
    brand = _brand(tmp_path / ".brand")
    _materials(brand)
    result = intake.take_in(brand)
    assert isinstance(result, intake.Manifest)
    assert result.brand == "acme"
    assert result.schema_version == 1
    assert all(isinstance(entry, intake.MaterialEntry) for entry in result.files)
    assert [(e.path, e.role, e.type, e.pages, e.format) for e in result.files] == [
        ("materials/examples/report.pdf", "examples", "pdf", 2, "doc"),
        ("materials/fonts/Inter-Regular.ttf", "fonts", "ttf", None, None),
        ("materials/guidelines/book.pdf", "guidelines", "pdf", 3, "slides"),
        ("materials/logos/logo.svg", "logos", "svg", None, None),
        ("materials/notes/notes.md", "notes", "md", None, None),
        ("materials/templates/deck.pptx", "templates", "pptx", 2, "slides"),
        ("materials/templates/memo.dotx", "templates", "dotx", 4, "doc"),
    ]
    for entry in result.files:
        contents = (brand / entry.path).read_bytes()
        assert entry.sha256 == hashlib.sha256(contents).hexdigest()
        assert entry.size == len(contents)
        assert entry.unread is None


def test_D2_manifest_persists_deterministically_and_tracks_changed_file(tmp_path):
    _require_intake()
    brand = _brand(tmp_path / ".brand")
    _materials(brand)
    first = intake.take_in(brand)
    path = brand / "theme/ingest/manifest.json"
    original = path.read_bytes()
    assert original.endswith(b"\n")
    assert intake.Manifest.model_validate_json(original) == first
    assert intake.take_in(brand) == first
    assert path.read_bytes() == original
    _pdf(brand / "materials/examples/report.pdf", 595, 842, 2, "Changed report")
    updated = intake.take_in(brand)
    before = {entry.path: entry.sha256 for entry in first.files}
    after = {entry.path: entry.sha256 for entry in updated.files}
    assert before.keys() == after.keys()
    assert [name for name in before if before[name] != after[name]] == ["materials/examples/report.pdf"]
    assert intake.Manifest.model_validate_json(path.read_bytes()) == updated


def test_D3_unreadable_and_unsorted_materials_are_recorded(tmp_path):
    _require_intake()
    brand = _brand(tmp_path / ".brand")
    materials = brand / "materials"
    (materials / "examples").mkdir(parents=True, exist_ok=True)
    (materials / "templates").mkdir(parents=True, exist_ok=True)
    (materials / "brand.key").write_bytes(b"keynote")
    (materials / "examples/broken.pdf").write_bytes(b"not a pdf")
    (materials / "templates/fake.pptx").write_bytes(b"not a zip")
    (materials / ".hidden").mkdir()
    (materials / ".hidden/ignored.txt").write_text("hidden")
    (materials / "examples/.ignored.txt").write_text("hidden")
    entries = {entry.path: entry for entry in intake.take_in(brand).files}
    assert set(entries) == {"materials/brand.key", "materials/examples/broken.pdf", "materials/templates/fake.pptx"}
    key = entries["materials/brand.key"]
    assert (key.role, key.type) == ("unsorted", "other")
    assert key.unread and "PowerPoint" in key.unread
    pdf = entries["materials/examples/broken.pdf"]
    assert pdf.pages is None and pdf.format is None and pdf.unread
    assert entries["materials/templates/fake.pptx"].unread


def test_D4_cli_records_intake_and_refuses_unknown_or_empty_brand(tmp_path, capsys):
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    assert changes is not None and hasattr(changes, "change_log"), "change_log must exist"
    root = tmp_path / ".brand"
    brand = _brand(root)
    _materials(brand)
    assert cli.main(["brand", "intake", "acme", "--root", str(root)]) == 0
    output = capsys.readouterr().out
    assert "7 files" in output
    for role in ("examples", "fonts", "guidelines", "logos", "notes", "templates"):
        assert role in output
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    def git(*args):
        return subprocess.run(["git", *args], cwd=brand, env=env, capture_output=True, text=True, check=True).stdout.strip()
    assert git("branch", "--show-current") == "main"
    assert git("status", "--porcelain") == ""
    records = changes.change_log(brand)
    assert len(records) == 1
    assert records[0].what == "Take in materials"
    assert {"theme/ingest/manifest.json", "materials/guidelines/book.pdf"} <= set(records[0].files)
    assert cli.main(["brand", "intake", "unknown", "--root", str(root)]) == 2
    workspace.init_brand("empty", root)
    assert cli.main(["brand", "intake", "empty", "--root", str(root)]) == 2
    assert "no materials" in capsys.readouterr().out.lower()
    assert changes.change_log(root / "empty") == []
