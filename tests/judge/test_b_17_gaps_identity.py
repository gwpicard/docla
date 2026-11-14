# Intent: Record material gaps and establish which identity the materials describe before learning.
import importlib
import importlib.util
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import yaml

from docla import cli
from docla.render.typst import compile_pdf


def _optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name or ""
        if name == missing or name.startswith(missing + "."):
            try:
                spec = importlib.util.find_spec(missing)
            except (ImportError, ModuleNotFoundError, ValueError):
                spec = None
            if spec is None:
                return None
        raise


gaps = _optional("docla.brand.gaps")
intake = _optional("docla.brand.intake")
questions = _optional("docla.brand.questions")
FONTS = Path(__file__).resolve().parents[2] / "src/docla/themes/neutral/fonts"


def _interfaces(*names):
    for module, members in names:
        assert module is not None, "The required brand interface must exist"
        for member in members:
            assert hasattr(module, member), f"The public interface {member} must exist"


def _pdf(path, text, *, slides=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    source = path.with_suffix(".typ")
    dimensions = '#set page(width: 960pt, height: 540pt)\n' if slides else ''
    source.write_text(dimensions + '#set text(font: "Inter")\n' + text, encoding="utf-8")
    compile_pdf(source, path.parent, path, font_paths=[FONTS])
    source.unlink()


def _brand(tmp_path, capsys, *, identity=True, materials=True):
    _interfaces((gaps, ["find_gaps", "read_identity", "check_gaps"]), (intake, ["take_in"]))
    root = tmp_path / ".brand"
    assert cli.main(["brand", "init", "acme", "--root", str(root)]) == 0
    capsys.readouterr()
    brand = root / "acme"
    if materials:
        text = 'Acme brand guidelines\n\nVersion 3.2\n\nMarch 2025' if identity else 'Acme brand guidelines'
        _pdf(brand / "materials/guidelines/book.pdf", text)
        template = brand / "materials/templates/deck.pptx"
        template.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(template, "w") as archive:
            archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
            archive.writestr("ppt/presentation.xml", '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>')
        _pdf(brand / "materials/examples/deck.pdf", "Example deck", slides=True)
        font = brand / "materials/fonts/Inter-Regular.ttf"
        font.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FONTS / "Inter-Regular.ttf", font)
    return brand


def _stored(brand):
    return yaml.safe_load((brand / "theme/ingest/questions.yaml").read_text(encoding="utf-8"))["questions"]


def test_D1_gap_order_formats_and_unreadable_guidelines(tmp_path, capsys):
    brand = _brand(tmp_path, capsys)
    found = gaps.find_gaps(intake.take_in(brand))
    assert [(g.kind, g.format) for g in found] == [
        ("no-word-template", "doc"), ("no-doc-examples", "doc"), ("no-logo", None)
    ]
    empty = _brand(tmp_path / "empty", capsys, materials=False)
    assert [g.kind for g in gaps.find_gaps(intake.take_in(empty))] == [
        "no-guidelines", "no-slide-template", "no-word-template", "no-slide-examples",
        "no-doc-examples", "no-logo", "no-fonts",
    ]
    bad = empty / "materials/guidelines/broken.pdf"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not a pdf")
    assert "no-guidelines" in [g.kind for g in gaps.find_gaps(intake.take_in(empty))]


def test_D2_identity_reads_version_date_and_missing_values(tmp_path, capsys):
    brand = _brand(tmp_path, capsys)
    _pdf(brand / "materials/guidelines/other.pdf", "Other guidelines")
    identities = gaps.read_identity(brand, intake.take_in(brand))
    assert [i.file for i in identities] == ["materials/guidelines/book.pdf", "materials/guidelines/other.pdf"]
    book, other = identities
    assert (book.version, book.date, book.page) == ("3.2", "March 2025", 1)
    assert book.quote is not None and "3.2" in book.quote
    assert (other.version, other.date) == (None, None)


def test_D3_questions_include_identity_and_preserve_fonts(tmp_path, capsys):
    _interfaces((questions, ["BrandQuestion", "add_questions"]))
    brand = _brand(tmp_path, capsys)
    intake.take_in(brand)
    questions.add_questions(brand, [questions.BrandQuestion(id="font.missing.inter", kind="font", text="Supply Inter")])
    gaps.check_gaps(brand)
    stored = {q["id"]: q for q in _stored(brand)}
    assert {"font.missing.inter", "gap.no-word-template", "gap.no-doc-examples", "gap.no-logo", "identity.earlier"} <= stored.keys()
    assert stored["font.missing.inter"]["kind"] == "font"
    assert (stored["gap.no-word-template"]["kind"], stored["gap.no-word-template"]["format"]) == ("gap", "doc")
    earlier = stored["identity.earlier"]
    assert earlier["kind"] == "identity" and earlier["blocking"] is True
    assert "3.2" in earlier["text"] and "March 2025" in earlier["text"]
    assert earlier["source"]["file"] == "materials/guidelines/book.pdf" and earlier["source"]["page"] == 1
    assert "identity.version" not in stored and "identity.date" not in stored
    no_identity = _brand(tmp_path / "other", capsys, identity=False)
    intake.take_in(no_identity)
    gaps.check_gaps(no_identity)
    assert {"identity.version", "identity.date"} <= {q["id"] for q in _stored(no_identity)}


def test_D4_recheck_preserves_decisions_and_removes_resolved_open_gaps(tmp_path, capsys):
    _interfaces((questions, ["drop_open_questions"]))
    brand = _brand(tmp_path, capsys)
    intake.take_in(brand)
    gaps.check_gaps(brand)
    path = brand / "theme/ingest/questions.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    answer = next(q for q in data["questions"] if q["id"] == "gap.no-word-template")
    answer.update(answer="We make no Word documents", answered_by="owner")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert questions.drop_open_questions(brand, ["gap.no-word-template"]) == []
    logo = brand / "materials/logos/logo.svg"
    logo.parent.mkdir(parents=True, exist_ok=True)
    logo.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>', encoding="utf-8")
    intake.take_in(brand)
    gaps.check_gaps(brand)
    stored = _stored(brand)
    ids = [q["id"] for q in stored]
    assert len(ids) == len(set(ids))
    assert "gap.no-logo" not in ids
    assert {"gap.no-word-template", "gap.no-doc-examples", "identity.earlier"} <= set(ids)
    answer = next(q for q in stored if q["id"] == "gap.no-word-template")
    assert (answer["answer"], answer["answered_by"]) == ("We make no Word documents", "owner")


def test_D5_cli_records_change_and_rejects_missing_manifest(tmp_path, capsys):
    brand = _brand(tmp_path, capsys)
    intake.take_in(brand)
    assert cli.main(["brand", "gaps", "acme", "--root", str(brand.parent)]) == 0
    output = capsys.readouterr().out
    assert "no-word-template" in output and "3.2" in output
    report = json.loads((brand / "theme/ingest/gaps.json").read_text(encoding="utf-8"))
    assert set(report) >= {"gaps", "identity"}
    assert subprocess.run(["git", "branch", "--show-current"], cwd=brand, capture_output=True, text=True, check=True).stdout.strip() == "main"
    assert subprocess.run(["git", "status", "--porcelain"], cwd=brand, capture_output=True, text=True, check=True).stdout == ""
    assert cli.main(["brand", "log", "acme", "--root", str(brand.parent)]) == 0
    assert "Record what the brand does not provide" in capsys.readouterr().out
    empty = _brand(tmp_path / "missing", capsys, materials=False)
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=empty, capture_output=True, text=True, check=True).stdout
    assert cli.main(["brand", "gaps", "acme", "--root", str(empty.parent)]) == 2
    after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=empty, capture_output=True, text=True, check=True).stdout
    assert after == before
