# Intent: Give each brand an isolated local workspace before learning from its materials.
import importlib
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from docla import cli
from docla.theme import ThemeError, load_theme
from docla.theme.models import ThemeInfo


def _brand_module(name):
    if importlib.util.find_spec("docla.brand") is None:
        return None
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        if importlib.util.find_spec(name) is not None:
            raise
        return None


git_module = _brand_module("docla.brand.git")
workspace = _brand_module("docla.brand.workspace")


def _init(slug, root):
    assert workspace is not None, "docla.brand.workspace must exist"
    assert hasattr(workspace, "init_brand"), "init_brand must exist"
    return cli.main(["brand", "init", slug, "--root", str(root)])


def _git(repo, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(["git", *args], cwd=repo, env=env, text=True, capture_output=True, check=True).stdout.strip()


def test_D1_workspace_layout_and_theme(tmp_path, capsys):
    root = tmp_path / ".brand"
    assert _init("acme", root) == 0
    brand = root / "acme"
    assert str(brand) in capsys.readouterr().out
    for folder in (
        "materials/guidelines",
        "materials/templates",
        "materials/examples",
        "materials/logos",
        "materials/fonts",
        "materials/notes",
        "theme/fonts",
        "reports",
    ):
        assert (brand / folder / ".gitkeep").is_file()
    assert "reports/*/.docla/" in (brand / ".gitignore").read_text().splitlines()
    info = ThemeInfo.model_validate(yaml.safe_load((brand / "theme/theme.yaml").read_text()))
    assert (info.name, info.version, info.formats) == ("acme", "0.1.0", ["slides", "doc"])
    assert not (brand / "theme/tokens.yaml").exists()
    with pytest.raises(ThemeError, match="tokens.yaml"):
        load_theme(brand / "theme")


def test_D2_isolated_repository_without_identity(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    outer = tmp_path / "outer"
    outer.mkdir()
    _git(outer, "init", "-b", "main")
    (outer / "original").write_text("original")
    _git(outer, "add", "original")
    _git(outer, "-c", "user.name=outer", "-c", "user.email=outer@example.com", "commit", "-m", "outer")
    head = _git(outer, "rev-parse", "HEAD")
    assert _git(outer, "rev-list", "--count", "HEAD") == "1"
    root = outer / ".brand"
    assert _init("acme", root) == 0
    brand = root / "acme"
    assert Path(_git(brand, "rev-parse", "--show-toplevel")).resolve() == brand.resolve()
    assert _git(brand, "branch", "--show-current") == "main"
    assert _git(brand, "log", "--format=%s") == "Start brand acme"
    assert _git(brand, "log", "-1", "--format=%an <%ae>") == "docla <docla@localhost>"
    assert _git(brand, "status", "--porcelain") == ""
    assert _git(outer, "rev-parse", "HEAD") == head
    assert _git(outer, "rev-list", "--count", "HEAD") == "1"


def test_D3_inherited_git_environment_is_ignored(tmp_path, monkeypatch):
    assert git_module is not None and hasattr(git_module, "run_git"), "run_git must exist"
    root = tmp_path / ".brand"
    assert _init("acme", root) == 0
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-b", "main")
    (other / "file").write_text("other")
    _git(other, "add", "file")
    _git(other, "-c", "user.name=other", "-c", "user.email=other@example.com", "commit", "-m", "other")
    head = _git(other, "rev-parse", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    assert git_module.run_git(root / "acme", "log", "--format=%s").strip() == "Start brand acme"
    assert _init("beta", root) == 0
    assert _git(root / "beta", "log", "--format=%s") == "Start brand beta"
    assert _git(other, "rev-parse", "HEAD") == head
    assert _git(other, "rev-list", "--count", "HEAD") == "1"


def test_D4_existing_brand_is_unchanged(tmp_path, capsys):
    root = tmp_path / ".brand"
    assert _init("acme", root) == 0
    brand = root / "acme"
    head = _git(brand, "rev-parse", "HEAD")
    before = sorted(str(path.relative_to(brand)) for path in brand.rglob("*") if ".git" not in path.parts)
    capsys.readouterr()
    assert _init("acme", root) == 2
    assert capsys.readouterr().err.strip()
    assert _git(brand, "rev-parse", "HEAD") == head
    assert _git(brand, "rev-list", "--count", "HEAD") == "1"
    assert _git(brand, "status", "--porcelain") == ""
    assert sorted(str(path.relative_to(brand)) for path in brand.rglob("*") if ".git" not in path.parts) == before


@pytest.mark.parametrize("slug", ["Acme", "acme corp", "../acme", "-acme", ""])
def test_D4_invalid_slug_creates_nothing(tmp_path, capsys, slug):
    root = tmp_path / ".brand"
    assert _init(slug, root) == 2
    assert capsys.readouterr().err.strip()
    assert list(tmp_path.iterdir()) == [] or (list(tmp_path.iterdir()) == [root] and list(root.iterdir()) == [])


def test_D5_default_root_and_brand_path(tmp_path, monkeypatch):
    assert workspace is not None, "docla.brand.workspace must exist"
    assert hasattr(workspace, "brand_path") and hasattr(workspace, "BrandError")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["brand", "init", "beta"]) == 0
    root = tmp_path / ".brand"
    assert (root / "beta").is_dir()
    assert workspace.brand_path("beta", root) == root / "beta"
    with pytest.raises(workspace.BrandError):
        workspace.brand_path("gamma", root)


def test_D6_repository_ignores_brands():
    repository = Path(__file__).resolve().parents[2]
    assert ".brand/" in (repository / ".gitignore").read_text().splitlines()
