"""Append-only records of section healing and finished sections."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ValidationError

from docla.facts.raster import crop
from docla.loop.router import ACTIONABLE
from docla.model import Section

if TYPE_CHECKING:
    from docla.loop.micro import SectionResult, SectionState


class HealEntry(BaseModel):
    t: str
    scope: str
    attempt: int
    findings_before: list[str]
    action: str
    patch_id: str | None
    findings_after: list[str]
    phi: list[int]
    cost_usd: float
    images: dict[str, str]
    status: Literal["clean", "residual"] | None = None
    section: dict[str, Any] | None = None


def _entries(path: Path) -> Iterator[HealEntry]:
    if not path.exists():
        return
    with path.open("rb") as stream:
        for line in stream:
            try:
                yield HealEntry.model_validate_json(line.decode("utf-8"))
            except (UnicodeDecodeError, ValidationError):
                continue


def _needs_newline(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("rb") as stream:
        stream.seek(-1, 2)
        return stream.read(1) != b"\n"


class HealLog:
    def __init__(self, run_dir: Path, *, now: Callable[[], datetime] | None = None) -> None:
        self.run_dir = run_dir
        self.path = run_dir / "heal.jsonl"
        self.now = now or (lambda: datetime.now(UTC))

    def _write(self, entry: HealEntry) -> HealEntry:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        prefix = "\n" if _needs_newline(self.path) else ""
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(prefix + entry.model_dump_json() + "\n")
        return entry

    def _image(self, state: SectionState, attempt: int, side: str) -> str | None:
        if state.render is None:
            return None
        page = state.render.facts.pages[0]
        box = (0.0, 0.0, page.width, page.height)
        for finding in state.findings:
            if finding.remedy.class_ in ACTIONABLE and finding.region is not None:
                region = finding.region
                box = (region.x, region.y, region.x + region.w, region.y + region.h)
                break
        relative = Path("heal") / f"{state.section.id}-{attempt}-{side}.png"
        (self.run_dir / "heal").mkdir(parents=True, exist_ok=True)
        crop(state.render.pngs[0], box, self.run_dir / relative)
        return relative.as_posix()

    def attempt(
        self, before: SectionState, after: SectionState, *, cost_usd: float = 0.0, patch_id: str | None = None
    ) -> HealEntry:
        images = {}
        for side, state in (("before", before), ("after", after)):
            path = self._image(state, after.attempt, side)
            if path is not None:
                images[side] = path
        return self._write(
            HealEntry(
                t=self._time(),
                scope=f"section:{after.section.id}",
                attempt=after.attempt,
                findings_before=[f.id for f in before.findings],
                action=after.action,
                patch_id=patch_id,
                findings_after=[f.id for f in after.findings],
                phi=[before.phi, after.phi],
                cost_usd=cost_usd,
                images=images,
            )
        )

    def _time(self) -> str:
        return self.now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    def finish(self, result: SectionResult, *, cost_usd: float = 0.0) -> HealEntry:
        state = result.state
        return self._write(
            HealEntry(
                t=self._time(),
                scope=f"section:{state.section.id}",
                attempt=result.attempts,
                findings_before=[f.id for f in state.findings],
                action=result.status,
                patch_id=None,
                findings_after=[f.id for f in state.findings],
                phi=[state.phi, state.phi],
                cost_usd=cost_usd,
                images={},
                status=result.status,
                section=state.section.model_dump(mode="json"),
            )
        )

    def _finished_entries(self) -> dict[str, HealEntry]:
        return {
            entry.scope.removeprefix("section:"): entry
            for entry in _entries(self.path)
            if entry.scope.startswith("section:") and entry.status is not None and entry.section is not None
        }

    def finished(self) -> dict[str, Section]:
        return {key: Section.model_validate(entry.section) for key, entry in self._finished_entries().items()}


def resume(run_dir: Path) -> set[str]:
    return set(HealLog(run_dir)._finished_entries())
