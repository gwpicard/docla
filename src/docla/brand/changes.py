"""Record and merge reviewable brand changes."""

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from docla.brand.git import run_git
from docla.brand.workspace import BrandError
from docla.model.source import Format


class Evidence(BaseModel):
    file: str
    page: int | None = None
    quote: str | None = None
    note: str | None = None


class ChangeRecord(BaseModel):
    id: str
    what: str
    why: str
    evidence: list[Evidence]
    files: list[str]
    before: list[str]
    after: list[str]
    formats: list[Format] = Field(min_length=1)
    person: str
    created: str
    branch: str

    @field_validator("formats")
    @classmethod
    def unique_formats(cls, value: list[Format]) -> list[Format]:
        if len(value) != len(set(value)):
            raise ValueError("Formats must not repeat")
        return value


def begin_change(brand: Path, name: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", name):
        raise BrandError(f"Invalid change name: {name!r}")
    if run_git(brand, "branch", "--show-current").strip() != "main":
        raise BrandError("A change can only begin on main")
    names = [path.parent.name for path in (brand / "changes").glob("*/record.json")]
    names += run_git(brand, "for-each-ref", "--format=%(refname:strip=3)", "refs/heads/change/").splitlines()
    numbers = [int(match.group(1)) for name in names if (match := re.match(r"^(\d+)-", name))]
    branch = f"change/{max(numbers, default=0) + 1:04d}-{name}"
    run_git(brand, "checkout", "-b", branch)
    return branch


def _changed_files(brand: Path) -> list[str]:
    entries = iter(run_git(brand, "status", "--porcelain", "-uall", "-z").split("\0"))
    paths = []
    for entry in entries:
        if not entry:
            continue
        path = entry[3:]
        if "R" in entry[:2] or "C" in entry[:2]:
            next(entries, None)
        if not path.startswith("changes/"):
            paths.append(path)
    return sorted(paths)


def _check_renders(paths: list[Path]) -> None:
    for path in paths:
        try:
            with path.open("rb") as stream:
                valid = stream.read(8) == b"\x89PNG\r\n\x1a\n"
        except OSError:
            valid = False
        if not valid:
            raise BrandError(f"Not a PNG file: {path}")


def _store_renders(brand: Path, change_id: str, kind: str, paths: list[Path]) -> list[str]:
    stored = []
    for number, source in enumerate(paths, 1):
        relative = Path("changes") / change_id / kind / f"{number:02d}.png"
        destination = brand / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        stored.append(relative.as_posix())
    return stored


def record_change(
    brand: Path,
    *,
    what: str,
    why: str,
    evidence: list[Evidence],
    before: list[Path],
    after: list[Path],
    formats: list[Format],
    person: str = "owner",
) -> ChangeRecord:
    branch = run_git(brand, "branch", "--show-current").strip()
    if not branch.startswith("change/"):
        raise BrandError("A change branch is required")
    if not what.strip() or not why.strip() or not evidence or not formats:
        raise BrandError("What, why, evidence and formats are required")
    if len(formats) != len(set(formats)) or any(item not in ("slides", "doc") for item in formats):
        raise BrandError("Invalid formats")
    _check_renders(before + after)
    files = _changed_files(brand)
    if not files:
        raise BrandError("Nothing to record")
    change_id = branch.removeprefix("change/")
    before_paths = _store_renders(brand, change_id, "before", before)
    after_paths = _store_renders(brand, change_id, "after", after)
    record = ChangeRecord(
        id=change_id,
        what=what,
        why=why,
        evidence=evidence,
        files=files,
        before=before_paths,
        after=after_paths,
        formats=formats,
        person=person,
        created=datetime.now(UTC).isoformat(),
        branch=branch,
    )
    record_path = brand / "changes" / change_id / "record.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(record.model_dump_json(indent=2))
    run_git(brand, "add", "-A")
    run_git(brand, "commit", "-m", what)
    run_git(brand, "checkout", "main")
    run_git(brand, "merge", "--no-ff", branch, "-m", f"Change {change_id}: {what}")
    return record


def change_log(brand: Path) -> list[ChangeRecord]:
    records = [ChangeRecord.model_validate_json(path.read_text()) for path in (brand / "changes").glob("*/record.json")]
    return sorted(records, key=lambda record: int(record.id.split("-", 1)[0]))
