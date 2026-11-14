from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from docla.model import Document, Format
from docla.render.chooser import Chooser, load_chooser
from docla.render.components import all_manifests
from docla.render.compose import default_chooser

ANY_INTENT = "any"


class DoctypeError(ValueError):
    """A doctype file is malformed or names an intent the chooser cannot draw."""


def _check_range(what: str, bounds: tuple[int, int]) -> None:
    if bounds[0] > bounds[1]:
        raise ValueError(f"{what} {list(bounds)}: min is above max")


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    ask: str


class OutlineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    section: str
    intent: str | None = None
    required: bool = False
    repeat: tuple[int, int] | None = None
    fill: Literal["facts", "summary", "fixed"] = "facts"
    from_: list[str] = Field(default_factory=list, alias="from")
    children: list["OutlineEntry"] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "OutlineEntry":
        if self.intent is None and not self.children:
            raise ValueError(f"section {self.section!r} has neither intent nor children")
        if self.repeat is not None:
            _check_range(f"section {self.section!r}: repeat", self.repeat)
        return self


class RuleRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str
    params: dict[str, Any] = Field(default_factory=dict)


class Doctype(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    format: Format
    audience: str
    length: dict[str, tuple[int, int]]
    questions: list[Question]
    outline: list[OutlineEntry]
    checks: list[RuleRef]
    checklist: list[str]

    @model_validator(mode="after")
    def _check(self) -> "Doctype":
        for unit, bounds in self.length.items():
            _check_range(f"length {unit!r}", bounds)
        return self


class Gap(BaseModel):
    kind: Literal["missing", "order", "repeat"]
    section: str
    message: str


def conformance(doc: Document, doctype: Doctype) -> list[Gap]:
    """Compare labelled document sections with the top-level outline."""
    positions = {entry.section: index for index, entry in enumerate(doctype.outline)}
    names = [section.section for section in doc.sections if section.section in positions]
    gaps = [
        Gap(kind="missing", section=entry.section, message=f"required section {entry.section} is missing")
        for entry in doctype.outline
        if entry.required and entry.section not in names
    ]
    highest = -1
    for name in names:
        assert name is not None
        position = positions[name]
        if position < highest:
            gaps.append(Gap(kind="order", section=name, message=f"section {name} is out of outline order"))
            break
        highest = position
    for entry in doctype.outline:
        if entry.repeat is not None and not entry.repeat[0] <= names.count(entry.section) <= entry.repeat[1]:
            gaps.append(
                Gap(
                    kind="repeat",
                    section=entry.section,
                    message=f"section {entry.section} is outside its repeat bounds",
                )
            )
    return gaps


def load_doctype(path: Path, chooser: Chooser | None = None) -> Doctype:
    """Read and check the doctype at `path` against `chooser` (default the packaged one)."""
    doctype = _read(path)
    if doctype.name != path.stem:
        raise DoctypeError(f"{path.name}: name {doctype.name!r} differs from the file stem {path.stem!r}")
    _check_intents(path, doctype.format, doctype.outline, default_chooser() if chooser is None else chooser)
    return doctype


def _read(path: Path) -> Doctype:
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        return Doctype.model_validate(data)
    except (yaml.YAMLError, ValidationError) as error:
        raise DoctypeError(f"{path.name}: not valid: {error}") from error


def _check_intents(path: Path, fmt: Format, outline: list[OutlineEntry], chooser: Chooser) -> None:
    for entry in outline:
        if entry.intent not in (None, ANY_INTENT) and not chooser.knows(entry.intent, fmt):
            raise DoctypeError(
                f"{path.name}: section {entry.section!r} has intent {entry.intent!r}, "
                f"which the chooser has no entries for in format {fmt!r}"
            )
        _check_intents(path, fmt, entry.children, chooser)


def packaged_dir() -> Path:
    """Return the folder of the packaged doctype files."""
    return Path(__file__).parent


def load_doctypes() -> dict[str, Doctype]:
    """Load every packaged doctype, keyed by name."""
    loaded = (load_doctype(path) for path in sorted(packaged_dir().glob("*.yaml")))
    return {doctype.name: doctype for doctype in loaded}


def library_dir() -> Path:
    return packaged_dir() / "library"


def load_library_doctypes(chooser: Chooser | None = None) -> dict[str, Doctype]:
    packaged = load_doctypes()
    result: dict[str, Doctype] = {}
    for path in sorted(library_dir().glob("*.yaml")):
        doctype = load_doctype(path, chooser)
        if doctype.name in packaged:
            raise DoctypeError(f"{path.name}: duplicates a top-level packaged doctype")
        result[doctype.name] = doctype
    return result


def packaged_doctypes(chooser: Chooser | None = None) -> dict[str, Doctype]:
    return {**load_doctypes(), **load_library_doctypes(chooser)}


def theme_doctypes_dir(theme_root: Path) -> Path:
    return theme_root / "doctypes"


def theme_chooser(theme_root: Path) -> Chooser:
    path = theme_root / "chooser.yaml"
    return load_chooser(path, manifests=all_manifests()) if path.exists() else default_chooser()


def load_brand_doctypes(theme_root: Path, chooser: Chooser | None = None) -> dict[str, Doctype]:
    paths = sorted(theme_doctypes_dir(theme_root).glob("*.yaml"))
    if not paths:
        return {}
    selected = chooser or theme_chooser(theme_root)
    loaded = (load_doctype(path, selected) for path in paths)
    return {doctype.name: doctype for doctype in loaded}


def doctypes_for(theme_root: Path | None = None, chooser: Chooser | None = None) -> dict[str, Doctype]:
    result = packaged_doctypes()
    if theme_root is not None:
        result.update(load_brand_doctypes(theme_root, chooser))
    return result
