# Intent: Map brand pages to component roles with traceable, recorded changes.
import importlib
import importlib.util
import os
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from docla.brand.workspace import BrandError, init_brand
from docla.render.typst import compile_pdf


def optional_module(name):
    if importlib.util.find_spec(name) is None:
        return None
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name == name or str(error.name).startswith(name + "."):
            return None
        raise


roles = optional_module("docla.brand.roles")
work = optional_module("docla.brand.work")
BOOK = "materials/guidelines/book.pdf"
REPORT = "materials/examples/report.pdf"
DECK = "materials/templates/deck.pptx"
LOGO = "materials/logos/logo.svg"


def require(module, *names):
    assert module is not None, "The public role mapping module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"
    return module


def git(brand, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=brand, env=env, text=True, capture_output=True, check=True).stdout.strip()


def make_pdf(brand, path, size, count, text="Example"):
    source = brand / "source.typ"
    source.write_text(f"#set page({size})\n" + "\n#pagebreak()\n".join([text] * count), encoding="utf-8")
    compile_pdf(source, brand, brand / path, [Path("src/docla/themes/neutral/fonts").resolve()])
    source.unlink()


def make_brand(tmp_path):
    require(roles, "set_roles", "load_roles")
    from docla.cli import main

    root = tmp_path / ".brand"
    folder = init_brand("acme", root)
    make_pdf(folder, BOOK, "width: 960pt, height: 540pt", 3)
    make_pdf(folder, REPORT, 'paper: "a4"', 2)
    with zipfile.ZipFile(folder / DECK, "w") as archive:
        for name in ("[Content_Types].xml", "ppt/slides/slide1.xml", "ppt/slides/slide2.xml"):
            archive.writestr(name, "<root/>")
    (folder / LOGO).write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    assert main(["brand", "intake", "acme", "--root", str(root)]) == 0
    assert main(["brand", "parse", "acme", "--root", str(root)]) == 0
    assert git(folder, "status", "--porcelain") == ""
    return folder


def test_D1_mapping_order_replacement_and_examples(tmp_path):
    brand = make_brand(tmp_path)
    from docla.brand.intake import Manifest

    api = require(roles, "examples_for")
    api.set_roles(brand, [(BOOK, 2, "cover"), (REPORT, 1, "body"), (DECK, 2, "chapter-break")], person="owner")
    assert (brand / "theme/ingest/roles.yaml").is_file()
    mappings = api.load_roles(brand).mappings
    assert [(m.file, m.page, m.format, m.component, m.person) for m in mappings] == [
        (REPORT, 1, "doc", "body", "owner"),
        (BOOK, 2, "slides", "cover", "owner"),
        (DECK, 2, "slides", "chapter-break", "owner"),
    ]
    manifest = Manifest.model_validate_json((brand / "theme/ingest/manifest.json").read_text())
    hashes = {entry.path: entry.sha256 for entry in manifest.files}
    assert all(m.sha256 == hashes[m.file] for m in mappings)
    updated = api.set_roles(brand, [(BOOK, 2, "statement")])
    assert [(m.file, m.page, m.component) for m in updated.mappings] == [
        (REPORT, 1, "body"),
        (BOOK, 2, "statement"),
        (DECK, 2, "chapter-break"),
    ]
    assert [(m.file, m.page) for m in api.examples_for(brand, "body")] == [(REPORT, 1)]


def test_D2_invalid_changes_are_atomic(tmp_path):
    brand = make_brand(tmp_path)
    api = require(roles, "set_roles")
    api.set_roles(brand, [(BOOK, 1, "cover")])
    path = brand / "theme/ingest/roles.yaml"
    original = path.read_bytes()
    cases = [
        ([(BOOK, 4, "cover")], None),
        ([(BOOK, 0, "cover")], None),
        ([(BOOK, 2, "body")], None),
        ([(REPORT, 1, "cover")], None),
        ([(BOOK, 2, "hero")], None),
        ([(LOGO, 1, "cover")], None),
        ([("materials/examples/missing.pdf", 1, "body")], None),
        ([(BOOK, 2, "cover"), (BOOK, 4, "cover")], None),
        ([], [(BOOK, 3)]),
    ]
    for mapped, unmapped in cases:
        with pytest.raises(BrandError):
            api.set_roles(brand, mapped, unmapped)
        assert path.read_bytes() == original


def test_D3_page_images_and_work_exclusion(tmp_path):
    brand = make_brand(tmp_path)
    from docla.brand.pages import load_pages

    api = require(roles, "page_png")
    work_api = require(work, "work_dir")
    entry = next(p for p in load_pages(brand).pages if (p.file, p.page) == (REPORT, 2))
    png = api.page_png(brand, REPORT, 2)
    assert png == brand / entry.png
    assert png.is_file() and png.is_relative_to(brand / "theme/ingest/work/pages")
    with Image.open(png) as image:
        assert abs(image.width - 909) <= 1
    for file, page in [(REPORT, 3), (DECK, 1)]:
        with pytest.raises(BrandError, match="parse"):
            api.page_png(brand, file, page)
    folder = work_api.work_dir(brand)
    assert folder == brand / "theme/ingest/work"
    assert work_api.work_dir(brand) == folder
    assert (brand / ".git/info/exclude").read_text().splitlines().count("/theme/ingest/work/") == 1
    (folder / "judge.txt").write_text("render", encoding="utf-8")
    assert git(brand, "status", "--porcelain") == ""


def test_D4_changed_material_is_stale(tmp_path):
    brand = make_brand(tmp_path)
    from docla.brand.intake import take_in

    api = require(roles, "stale_roles")
    api.set_roles(brand, [(REPORT, 1, "body"), (BOOK, 2, "cover")])
    make_pdf(brand, REPORT, 'paper: "a4"', 2, "Changed report")
    stale = api.stale_roles(brand, take_in(brand))
    assert [(m.file, m.page, m.component) for m in stale] == [(REPORT, 1, "body")]


def test_D5_cli_records_and_rejects_invalid_changes(tmp_path, capsys):
    brand = make_brand(tmp_path)
    from docla.brand.changes import change_log

    from docla.cli import main

    root = str(brand.parent)
    assert (
        main(["brand", "roles", "acme", "--root", root, "--map", f"{BOOK}:2=cover", "--map", f"{REPORT}:1=body"]) == 0
    )
    assert git(brand, "branch", "--show-current") == "main"
    assert git(brand, "status", "--porcelain") == ""
    records = change_log(brand)
    record = records[-1]
    assert record.what == "Map example pages to components"
    assert "theme/ingest/roles.yaml" in record.files
    assert record.formats == ["doc", "slides"]
    capsys.readouterr()
    assert main(["brand", "roles", "acme", "--root", root]) == 0
    output = capsys.readouterr().out
    assert "book.pdf p2" in output and "cover" in output
    assert main(["brand", "roles", "acme", "--root", root, "--map", f"{BOOK}:9=cover"]) == 2
    assert change_log(brand) == records
    assert git(brand, "branch", "--show-current") == "main"
    assert main(["brand", "roles", "unknown", "--root", root]) == 2
