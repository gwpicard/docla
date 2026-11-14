# Intent: Make brand changes reviewable and traceable through rendered history.

import importlib
import importlib.util
import os
import subprocess

import pytest
from PIL import Image


def _import_subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name is None or not (name == error.name or name.startswith(error.name + ".")):
            raise
        try:
            spec = importlib.util.find_spec(error.name)
        except ModuleNotFoundError as missing:
            if missing.name is None or not error.name.startswith(missing.name + "."):
                raise
            spec = None
        if spec is not None:
            raise
        return None


changes = _import_subject("docla.brand.changes")
workspace = _import_subject("docla.brand.workspace")
cli = _import_subject("docla.cli")


def _api():
    assert changes is not None, "docla.brand.changes must exist"
    assert workspace is not None, "docla.brand.workspace must exist"
    for name in ("Evidence", "ChangeRecord", "begin_change", "record_change", "change_log"):
        assert hasattr(changes, name), f"docla.brand.changes.{name} must exist"
    assert hasattr(workspace, "init_brand") and hasattr(workspace, "BrandError")
    return changes, workspace


def _git(brand, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=brand, env=env, check=True, capture_output=True, text=True).stdout.strip()


def _png(path, colour):
    Image.new("RGB", (3, 4), colour).save(path, format="PNG")
    return path


def _args(api, tmp_path):
    changes, _ = api
    return dict(
        what="Set the accent colour", why="The brand book states it",
        evidence=[changes.Evidence(file="materials/guidelines/book.pdf", page=4, quote="Accent: #0B5FFF")],
        before=[_png(tmp_path / "before.png", "red")], after=[_png(tmp_path / "after.png", "blue")],
        formats=["slides"], person="owner",
    )


def _edit(brand):
    (brand / "theme/notes.txt").write_text("Accent notes\n")
    with (brand / "theme/theme.yaml").open("a") as stream:
        stream.write("\n# accent colour\n")


def _first(api, tmp_path, brand):
    changes, _ = api
    assert changes.begin_change(brand, "accent-colour") == "change/0001-accent-colour"
    _edit(brand)
    args = _args(api, tmp_path)
    return changes.record_change(brand, **args), args


def _second(api, tmp_path, brand):
    changes, _ = api
    assert changes.begin_change(brand, "report-margins") == "change/0002-report-margins"
    (brand / "theme/margins.txt").write_text("A4 margins\n")
    args = _args(api, tmp_path)
    args.update(
        what="Set report margins", formats=["doc"],
        before=[_png(tmp_path / "before-1.png", "white"), _png(tmp_path / "before-2.png", "black")],
        after=[_png(tmp_path / "after-1.png", "green"), _png(tmp_path / "after-2.png", "yellow")],
    )
    return changes.record_change(brand, **args), args


def test_D1_begin_change_and_refusals(tmp_path):
    changes, workspace = _api()
    brand = workspace.init_brand("acme", tmp_path / ".brand")
    with pytest.raises(workspace.BrandError):
        changes.begin_change(brand, "Accent Colour")
    assert _git(brand, "branch", "--show-current") == "main"
    assert changes.begin_change(brand, "accent-colour") == "change/0001-accent-colour"
    assert _git(brand, "branch", "--show-current") == "change/0001-accent-colour"
    with pytest.raises(workspace.BrandError):
        changes.begin_change(brand, "other")
    assert _git(brand, "branch", "--show-current") == "change/0001-accent-colour"


def test_D2_record_merge_and_renders(tmp_path):
    api = _api()
    changes, workspace = api
    brand = workspace.init_brand("acme", tmp_path / ".brand")
    record, args = _first(api, tmp_path, brand)
    assert isinstance(record, changes.ChangeRecord)
    assert record.id == "0001-accent-colour"
    assert record.files == ["theme/notes.txt", "theme/theme.yaml"]
    assert record.before == ["changes/0001-accent-colour/before/01.png"]
    assert record.after == ["changes/0001-accent-colour/after/01.png"]
    assert record.formats == ["slides"] and record.person == "owner"
    assert _git(brand, "branch", "--show-current") == "main"
    parents = _git(brand, "rev-list", "--parents", "-n", "1", "HEAD").split()
    assert len(parents) == 3
    assert parents[2] == _git(brand, "rev-parse", "change/0001-accent-colour")
    assert _git(brand, "log", "-1", "--format=%s") == "Change 0001-accent-colour: Set the accent colour"
    assert (brand / record.before[0]).read_bytes() == args["before"][0].read_bytes()
    assert (brand / record.after[0]).read_bytes() == args["after"][0].read_bytes()
    assert changes.ChangeRecord.model_validate_json((brand / "changes/0001-accent-colour/record.json").read_text()) == record
    assert _git(brand, "status", "--porcelain") == ""


@pytest.mark.parametrize("case", ["what", "why", "evidence", "formats", "png", "nothing", "main"])
def test_D3_refusals_preserve_state(tmp_path, case):
    api = _api()
    changes, workspace = api
    brand = workspace.init_brand("acme", tmp_path / ".brand")
    if case != "main":
        changes.begin_change(brand, "accent-colour")
    if case != "nothing":
        _edit(brand)
    args = _args(api, tmp_path)
    if case in ("what", "why"):
        args[case] = "  "
    elif case in ("evidence", "formats"):
        args[case] = []
    elif case == "png":
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"not a PNG")
        args["before"] = [bad]
    branch = _git(brand, "branch", "--show-current")
    count = _git(brand, "rev-list", "--count", "HEAD")
    status = _git(brand, "status", "--porcelain", "-uall")
    def files():
        return {p.relative_to(brand): p.read_bytes() for p in brand.rglob("*")
                if p.is_file() and ".git" not in p.relative_to(brand).parts}
    original = files()
    with pytest.raises(workspace.BrandError):
        changes.record_change(brand, **args)
    assert _git(brand, "branch", "--show-current") == branch
    assert _git(brand, "rev-list", "--count", "HEAD") == count
    assert _git(brand, "status", "--porcelain", "-uall") == status
    assert files() == original


def test_D4_ordered_log_and_document_renders(tmp_path):
    api = _api()
    changes, workspace = api
    brand = workspace.init_brand("acme", tmp_path / ".brand")
    first, _ = _first(api, tmp_path, brand)
    second, args = _second(api, tmp_path, brand)
    assert second.id == "0002-report-margins"
    assert second.after == ["changes/0002-report-margins/after/01.png", "changes/0002-report-margins/after/02.png"]
    assert second.before == ["changes/0002-report-margins/before/01.png", "changes/0002-report-margins/before/02.png"]
    for stored, original in zip(second.before + second.after, args["before"] + args["after"], strict=True):
        assert (brand / stored).read_bytes() == original.read_bytes()
    records = changes.change_log(brand)
    assert records == [first, second]
    assert [record.what for record in records] == ["Set the accent colour", "Set report margins"]
    assert [record.formats for record in records] == [["slides"], ["doc"]]


def test_D5_cli_log(tmp_path, capsys):
    api = _api()
    _, workspace = api
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    root = tmp_path / ".brand"
    brand = workspace.init_brand("acme", root)
    assert cli.main(["brand", "log", "acme", "--root", str(root)]) == 0
    assert capsys.readouterr().out.strip() == "no changes"
    _first(api, tmp_path, brand)
    _second(api, tmp_path, brand)
    assert cli.main(["brand", "log", "acme", "--root", str(root)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("0001-accent-colour") and "Set the accent colour" in lines[0]
    assert lines[1].startswith("0002-report-margins")
    assert cli.main(["brand", "log", "missing", "--root", str(root)]) == 2
    captured = capsys.readouterr()
    assert captured.out or captured.err
