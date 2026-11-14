"""Keep regenerated brand work out of change records."""

from pathlib import Path

from docla.brand.pages import WORK
from docla.brand.workspace import BrandError


def work_dir(brand: Path) -> Path:
    git = brand / ".git"
    if not git.is_dir():
        raise BrandError(f"Brand git directory missing: {git}")
    exclude = git / "info/exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    content = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    line = "/theme/ingest/work/"
    if line not in content.splitlines():
        with exclude.open("a", encoding="utf-8") as stream:
            stream.write(("\n" if content and not content.endswith("\n") else "") + line + "\n")
    folder = brand / WORK
    folder.mkdir(parents=True, exist_ok=True)
    return folder
