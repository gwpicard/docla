# Intent: Check supplied brand fonts and licences without silently substituting typefaces.
import hashlib
import importlib
import importlib.util
import shutil
import subprocess
from pathlib import Path

import yaml


def subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name or ""
        if (name == missing or name.startswith(missing + ".") or missing.startswith(name + ".")) and (
            missing == "docla.brand" or missing.startswith("docla.brand.")
        ):
            try:
                spec = importlib.util.find_spec(missing)
            except ModuleNotFoundError:
                spec = None
            if spec is None:
                return None
        raise


fonts = subject("docla.brand.fonts")
questions = subject("docla.brand.questions")
workspace = subject("docla.brand.workspace")
changes = subject("docla.brand.changes")

NEUTRAL = Path(__file__).resolve().parents[2] / "src/docla/themes/neutral/fonts"
FILES = ["Inter-Regular.ttf", "Inter-SemiBold.ttf", "SourceSerif4-Regular.ttf"]


def prepare(brand, typefaces=None):
    folder = brand / "materials/fonts"
    folder.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copyfile(NEUTRAL / name, folder / name)
    labels = {
        "typefaces": typefaces if typefaces is not None else ["Inter", "Source Serif 4"],
        "fonts": [
            {"file": FILES[0], "family": "Inter", "weight": 400, "licence": "OFL-1.1"},
            {"file": FILES[1], "family": "Inter", "weight": 600, "licence": "OFL-1.1"},
            {"file": FILES[2], "family": "Source Serif 4", "weight": 400, "licence": "OFL-1.1"},
        ],
    }
    (folder / "fonts.yaml").write_text(yaml.safe_dump(labels), encoding="utf-8")
    return folder, labels


def test_D1_name_table_and_typefaces(tmp_path):
    assert fonts is not None and hasattr(fonts, "check_fonts"), "check_fonts must exist"
    prepare(tmp_path)
    report = fonts.check_fonts(tmp_path)
    assert [(f.file, f.family, f.weight, f.fs_type, f.embedding, f.status) for f in report.files] == [
        ("Inter-Regular.ttf", "Inter", 400, 0, "installable", "ok"),
        ("Inter-SemiBold.ttf", "Inter", 600, 0, "installable", "ok"),
        ("SourceSerif4-Regular.ttf", "Source Serif 4", 400, 0, "installable", "ok"),
    ]
    assert report.typefaces == {"Inter": FILES[:2], "Source Serif 4": [FILES[2]]}
    assert report.questions == []


def test_D2_missing_typeface_is_a_question(tmp_path):
    assert fonts is not None and hasattr(fonts, "check_fonts"), "check_fonts must exist"
    prepare(tmp_path, ["Inter", "Acme Sans"])
    report = fonts.check_fonts(tmp_path)
    assert report.typefaces == {"Inter": FILES[:2], "Acme Sans": []}
    assert len(report.questions) == 1
    q = report.questions[0]
    assert (q.id, q.kind, q.blocking, q.format) == ("font.missing.acme-sans", "font", True, None)
    assert "Acme Sans" in q.text


def test_D3_bad_files_and_install_filter(tmp_path):
    assert fonts is not None and hasattr(fonts, "check_fonts") and hasattr(fonts, "install_fonts")
    from fontTools.ttLib import TTFont

    folder, labels = prepare(tmp_path)
    labels["fonts"][0]["family"] = "Acme Sans"
    labels["fonts"][1]["licence"] = ""
    labels["fonts"].pop(2)
    restricted = TTFont(NEUTRAL / FILES[2])
    restricted["OS/2"].fsType = 2
    restricted.save(folder / "Restricted-Regular.ttf")
    restricted.close()
    labels["fonts"].append({"file": "Restricted-Regular.ttf", "family": "Source Serif 4", "weight": 400, "licence": "OFL-1.1"})
    (folder / "Broken.ttf").write_bytes(b"not a font")
    (folder / "Inter.woff2").write_bytes(b"not a font")
    shutil.copyfile(NEUTRAL / FILES[0], folder / "Good.ttf")
    labels["fonts"].append({"file": "Good.ttf", "family": "Inter", "weight": 400, "licence": "OFL-1.1"})
    (folder / "fonts.yaml").write_text(yaml.safe_dump(labels), encoding="utf-8")
    report = fonts.check_fonts(tmp_path, [])
    by_file = {f.file: f for f in report.files}
    expected = {"Inter-Regular.ttf": "mismatch", "Inter-SemiBold.ttf": "no-licence", "SourceSerif4-Regular.ttf": "unlabelled", "Restricted-Regular.ttf": "restricted", "Broken.ttf": "unreadable", "Inter.woff2": "unsupported", "Good.ttf": "ok"}
    assert {name: f.status for name, f in by_file.items()} == expected
    assert (by_file["Restricted-Regular.ttf"].fs_type, by_file["Restricted-Regular.ttf"].embedding) == (2, "restricted")
    by_id = {q.id: q for q in report.questions}
    assert set(by_id) == {f"font.{status}.{name}" for name, status in expected.items() if status != "ok"}
    for name, status in expected.items():
        if status != "ok":
            q = by_id[f"font.{status}.{name}"]
            assert q.kind == "font" and q.blocking and q.format is None
            assert q.source.file == f"materials/fonts/{name}"
            assert name in q.text
    assert "Inter" in by_id["font.mismatch.Inter-Regular.ttf"].text
    assert fonts.install_fonts(tmp_path, report) == ["Good.ttf"]
    assert (tmp_path / "theme/fonts/Good.ttf").read_bytes() == (folder / "Good.ttf").read_bytes()
    assert not (tmp_path / "theme/fonts/Restricted-Regular.ttf").exists()


def test_D4_install_records_are_replaced(tmp_path):
    assert fonts is not None and hasattr(fonts, "check_fonts") and hasattr(fonts, "install_fonts")
    folder, _ = prepare(tmp_path)
    report = fonts.check_fonts(tmp_path)
    assert fonts.install_fonts(tmp_path, report) == FILES
    assert fonts.install_fonts(tmp_path, report) == FILES
    target = tmp_path / "theme/fonts"
    records = (target / "LICENSES.txt").read_text(encoding="utf-8").strip().split("\n\n")
    assert len(records) == 3
    parsed = [dict(line.split(": ", 1) for line in record.splitlines()) for record in records]
    assert sum(record["file"] == "Inter-Regular.ttf" for record in parsed) == 1
    for f in report.files:
        assert (target / f.file).read_bytes() == (folder / f.file).read_bytes()
        assert f.sha256 == hashlib.sha256((folder / f.file).read_bytes()).hexdigest()
        record = next(r for r in parsed if r["file"] == f.file)
        assert record == {"file": f.file, "family": f.family, "weight": str(f.weight), "licence": "OFL-1.1", "fs_type": "0", "embedding": "installable", "sha256": f.sha256, "source": f"materials/fonts/{f.file}"}


def test_D5_question_deduplication_and_answer_preservation(tmp_path):
    assert fonts is not None and hasattr(fonts, "check_fonts")
    assert questions is not None and all(hasattr(questions, n) for n in ("add_questions", "load_questions", "open_questions"))
    prepare(tmp_path, ["Inter", "Acme Sans"])
    q = fonts.check_fonts(tmp_path).questions[0]
    assert questions.load_questions(tmp_path) == []
    assert questions.add_questions(tmp_path, [q]) == [q]
    assert questions.add_questions(tmp_path, [q]) == []
    path = tmp_path / "theme/ingest/questions.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(data["questions"]) == 1
    data["questions"][0]["answer"] = "Use Inter"
    data["questions"][0]["answered_by"] = "owner"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert questions.add_questions(tmp_path, [q.model_copy(update={"text": "Changed"})]) == []
    stored = questions.load_questions(tmp_path)
    assert len(stored) == 1
    assert (stored[0].text, stored[0].answer, stored[0].answered_by) == (q.text, "Use Inter", "owner")
    assert questions.open_questions(tmp_path) == []


def test_D6_cli_records_change_and_unknown_brand(tmp_path, capsys):
    assert fonts is not None and questions is not None
    assert workspace is not None and hasattr(workspace, "init_brand"), "init_brand must exist"
    assert changes is not None and hasattr(changes, "change_log"), "change_log must exist"
    from docla.cli import main

    root = tmp_path / ".brand"
    workspace.init_brand("acme", root)
    brand = root / "acme"
    prepare(brand, ["Inter", "Acme Sans"])
    assert main(["brand", "fonts", "acme", "--root", str(root)]) == 0
    output = capsys.readouterr().out
    assert any("Inter-Regular.ttf" in line and "installable" in line for line in output.splitlines())
    assert subprocess.check_output(["git", "branch", "--show-current"], cwd=brand, text=True).strip() == "main"
    assert subprocess.check_output(["git", "status", "--porcelain"], cwd=brand, text=True) == ""
    assert (brand / "theme/ingest/fonts.json").is_file()
    assert [q.id for q in questions.load_questions(brand)] == ["font.missing.acme-sans"]
    assert any(change.what == "Check the brand's fonts" for change in changes.change_log(brand))
    assert main(["brand", "fonts", "unknown", "--root", str(root)]) == 2
