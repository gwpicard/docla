"""Create and locate brand workspaces."""

import re
import shutil
from pathlib import Path

from docla.brand.git import init_repo, run_git

BRANDS_DIR = ".brand"
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
MATERIAL_CLASSES = ("guidelines", "templates", "examples", "logos", "fonts", "notes")


class BrandError(ValueError):
    """A brand workspace cannot be created or found."""


def default_root() -> Path:
    return Path.cwd() / BRANDS_DIR


def _validate_slug(slug: str) -> None:
    if not SLUG.fullmatch(slug):
        raise BrandError(f"Invalid brand slug: {slug!r}")


def brand_path(slug: str, root: Path | None = None) -> Path:
    _validate_slug(slug)
    path = (root if root is not None else default_root()) / slug
    if not path.is_dir() or not (path / ".git").exists():
        raise BrandError(f"Brand not found: {path}")
    return path


def _populate(path: Path, slug: str) -> None:
    for folder in [*(f"materials/{name}" for name in MATERIAL_CLASSES), "theme/fonts", "reports"]:
        directory = path / folder
        directory.mkdir(parents=True)
        (directory / ".gitkeep").touch()
    (path / "theme/theme.yaml").write_text(f"name: {slug}\nversion: 0.1.0\nformats: [slides, doc]\n")
    (path / ".gitignore").write_text("reports/*/.docla/\n")


def init_brand(slug: str, root: Path | None = None) -> Path:
    _validate_slug(slug)
    root = root if root is not None else default_root()
    path = root / slug
    root.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError as error:
        raise BrandError(f"Brand already exists: {path}") from error
    try:
        _populate(path, slug)
        init_repo(path)
        run_git(path, "add", "-A")
        run_git(path, "commit", "-m", f"Start brand {slug}")
    except BaseException:
        shutil.rmtree(path)
        raise
    return path
