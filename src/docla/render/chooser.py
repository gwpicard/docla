from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from docla.model import Format, Section
from docla.render.components import ComponentManifest, all_manifests

FORMATS: tuple[Format, ...] = ("slides", "doc")


class ChooserError(ValueError):
    """The chooser file is malformed, or it has no component for a section."""


class When(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: tuple[int, int] | None = None
    max_item_chars: tuple[int, int] | None = None
    has_data: bool | None = None
    has_image: bool | None = None
    is_first: bool | None = None
    is_last: bool | None = None

    def matches(self, section: Section, index: int, total: int) -> bool:
        """Return whether every key given here matches `section` at `index` of `total`."""
        features: dict[str, Any] = {
            "has_data": section.data is not None,
            "has_image": section.image is not None,
            "is_first": index == 0,
            "is_last": index == total - 1,
        }
        flags = all(getattr(self, key) in (None, value) for key, value in features.items())
        return flags and _within(self.count, len(section.items)) and _within(self.max_item_chars, _longest(section))


def _within(bounds: tuple[int, int] | None, value: int) -> bool:
    return bounds is None or bounds[0] <= value <= bounds[1]


def _longest(section: Section) -> int:
    return max((len(item.head or "") + len(item.body) for item in section.items), default=0)


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    when: When | None = None
    component: str | None


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    describes: str
    slides: list[Any] = Field(default_factory=list)
    doc: list[Any] = Field(default_factory=list)


class ChooserFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1, le=1)
    intents: dict[str, Intent]


class Chooser:
    """Maps a section's intent and content features to a component, per format."""

    def __init__(self, entries: dict[tuple[str, Format], list[Entry]], manifests: dict[str, ComponentManifest]):
        self.entries = entries
        self.manifests = manifests

    def choose(self, section: Section, fmt: Format, index: int, total: int) -> str | None:
        """Return the component of the first entry that matches; None means the section is prose."""
        entries = self.entries.get((section.intent, fmt))
        if entries is None:
            raise ChooserError(f"intent {section.intent!r} has no entries for format {fmt!r}")
        for entry in entries:
            if entry.when is None or entry.when.matches(section, index, total):
                return entry.component
        raise ChooserError(f"intent {section.intent!r}, format {fmt!r}: no entry matches section {section.id}")

    def alternates(self, section: Section, fmt: Format, index: int, total: int) -> list[str]:
        """Return distinct matching components after the first choice."""
        entries = self.entries.get((section.intent, fmt))
        if entries is None:
            raise ChooserError(f"intent {section.intent!r} has no entries for format {fmt!r}")
        matches = [entry.component for entry in entries if entry.when is None or entry.when.matches(section, index, total)]
        if not matches:
            return []
        seen = {matches[0]}
        result: list[str] = []
        for component in matches[1:]:
            if component is not None and component not in seen:
                result.append(component)
                seen.add(component)
        return result

    def knows(self, intent: str, fmt: Format) -> bool:
        """Return whether the chooser has entries for `intent` in format `fmt`."""
        return (intent, fmt) in self.entries

    def names(self, fmt: Format) -> set[str]:
        """Return the names of the components drawn in format `fmt`."""
        return {name for name, manifest in self.manifests.items() if manifest.format == fmt}


def default_path() -> Path:
    """Return the path of the packaged chooser file."""
    return Path(__file__).parent / "chooser.yaml"


def load_chooser(path: Path | None = None, manifests: dict[str, ComponentManifest] | None = None) -> Chooser:
    """Read and check the chooser at `path` (default the packaged one) against the component manifests."""
    manifests = all_manifests() if manifests is None else manifests
    data = _read(default_path() if path is None else path)
    entries: dict[tuple[str, Format], list[Entry]] = {}
    for name, intent in data.intents.items():
        for fmt in FORMATS:
            raw = getattr(intent, fmt)
            if raw:
                entries[(name, fmt)] = _entries(name, fmt, raw, manifests)
    return Chooser(entries, manifests)


def _read(path: Path) -> ChooserFile:
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return ChooserFile.model_validate(data)
    except (yaml.YAMLError, ValidationError) as error:
        raise ChooserError(f"{path.name}: not valid: {error}") from error


def _entries(intent: str, fmt: Format, raw: list[Any], manifests: dict[str, ComponentManifest]) -> list[Entry]:
    where = f"intent {intent!r}, format {fmt!r}"
    try:
        entries = [Entry.model_validate(item) for item in raw]
    except ValidationError as error:
        raise ChooserError(f"{where}: entry not valid: {error}") from error
    if any(entry.when is None for entry in entries[:-1]):
        raise ChooserError(f"{where}: an entry without `when` must be last")
    for entry in entries:
        _check_component(where, fmt, entry.component, manifests)
    return entries


def _check_component(where: str, fmt: Format, name: str | None, manifests: dict[str, ComponentManifest]) -> None:
    if name is None:
        return
    if name not in manifests:
        raise ChooserError(f"{where}: component {name!r} has no manifest")
    if manifests[name].format != fmt:
        raise ChooserError(f"{where}: component {name!r} is for format {manifests[name].format!r}")
