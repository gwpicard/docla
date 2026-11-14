import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from docla.model import Document, Format, Item, Section
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


class FixedText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    paragraphs: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "FixedText":
        if not any(value.strip() for value in [self.title or "", *self.paragraphs, *self.items]):
            raise ValueError("fixed text must contain non-blank text")
        return self


class OutlineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    section: str
    intent: str | None = None
    required: bool = False
    repeat: tuple[int, int] | None = None
    fill: Literal["facts", "summary", "fixed"] = "facts"
    from_: list[str] = Field(default_factory=list, alias="from")
    children: list["OutlineEntry"] = Field(default_factory=list)
    layouts: list[str] = Field(default_factory=list)
    text: FixedText | None = None

    @model_validator(mode="after")
    def _check(self) -> "OutlineEntry":
        if self.intent is None and not self.children:
            raise ValueError(f"section {self.section!r} has neither intent nor children")
        if self.repeat is not None:
            _check_range(f"section {self.section!r}: repeat", self.repeat)
        self._check_fixed()
        if len(self.layouts) != len(set(self.layouts)):
            raise ValueError(f"section {self.section!r}: duplicate layouts")
        return self

    def _check_fixed(self) -> None:
        if self.fill == "fixed":
            if self.text is None or self.intent in (None, ANY_INTENT) or self.children:
                raise ValueError(f"section {self.section!r}: fixed requires text, a concrete intent and no children")
        elif self.text is not None:
            raise ValueError(f"section {self.section!r}: text requires fixed fill")


class RuleRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str
    params: dict[str, Any] = Field(default_factory=dict)


class RequiredField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    ask: str

    @field_validator("key")
    @classmethod
    def _check_key(cls, value: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_]{0,40}", value) is None:
            raise ValueError("invalid required field key")
        return value


def length_unit(fmt: Format) -> Literal["slides", "pages"]:
    return "slides" if fmt == "slides" else "pages"


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
    required_fields: list[RequiredField] = Field(default_factory=list)
    default_length: int | None = Field(default=None, ge=1)
    twin: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "Doctype":
        for unit, bounds in self.length.items():
            _check_range(f"length {unit!r}", bounds)
        keys = [field.key for field in self.required_fields]
        if len(keys) != len(set(keys)):
            raise ValueError("required field keys must be unique")
        if self.twin == self.name:
            raise ValueError("twin must differ from name")
        if self.default_length is not None:
            bounds = self.length.get(length_unit(self.format))
            if bounds is None or not bounds[0] <= self.default_length <= bounds[1]:
                raise ValueError("default length must be within the format length range")
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
    selected = default_chooser() if chooser is None else chooser
    _check_intents(path, doctype.format, doctype.outline, selected)
    _check_layouts(path, doctype.format, doctype.outline, selected)
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


def walk(outline: list[OutlineEntry]) -> Iterator[OutlineEntry]:
    for entry in outline:
        yield entry
        yield from walk(entry.children)


def _check_layouts(path: Path, fmt: Format, outline: list[OutlineEntry], chooser: Chooser) -> None:
    for entry in walk(outline):
        if entry.intent is None:
            allowed: set[str | None] = set()
        elif entry.intent == ANY_INTENT:
            allowed = set(chooser.names(fmt))
        else:
            allowed = {item.component for item in chooser.entries[(entry.intent, fmt)]}
        for layout in entry.layouts:
            if layout not in allowed:
                raise DoctypeError(f"{path.name}: section {entry.section!r} has invalid layout {layout!r}")


def fixed_section(entry: OutlineEntry) -> Section:
    if entry.fill != "fixed" or entry.text is None or entry.intent is None:
        raise ValueError("entry is not fixed")
    return Section(
        intent=entry.intent,
        section=entry.section,
        component=entry.layouts[0] if entry.layouts else None,
        title=entry.text.title,
        paragraphs=entry.text.paragraphs,
        items=[Item(body=body) for body in entry.text.items],
        lock="all",
    )


def resolve_doctype(doctypes: Mapping[str, Doctype], name: str, fmt: Format) -> Doctype:
    doctype = doctypes.get(name)
    if doctype is None:
        raise DoctypeError(f"unknown doctype {name!r}")
    if doctype.format == fmt:
        return doctype
    twin = doctypes.get(doctype.twin) if doctype.twin is not None else None
    if twin is not None and twin.format == fmt:
        return twin
    raise DoctypeError(f"doctype {name!r} has no twin for format {fmt!r}")


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
