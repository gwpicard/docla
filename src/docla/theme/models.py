import re
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from docla.model.source import Format

PT_PER_UNIT = {"pt": 1.0, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72.0}
PAGE_SIZES = {"a4": (595.276, 841.89)}
LENGTH = re.compile(r"\s*(-?\d+(?:\.\d+)?)\s*(pt|mm|cm|in)\s*")
HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")


def to_pt(value: str | float) -> float:
    """Convert a length to points: a number is pt; a string is a number followed by pt, mm, cm or in."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        match = LENGTH.fullmatch(value)
        if match:
            return float(match.group(1)) * PT_PER_UNIT[match.group(2)]
    raise ValueError(f"not a length: {value!r} (use a number or a number followed by pt, mm, cm or in)")


Length = Annotated[float, BeforeValidator(to_pt)]


def to_colour(value: str) -> str:
    if not isinstance(value, str) or not HEX_COLOUR.fullmatch(value):
        raise ValueError(f"not a #RRGGBB colour: {value!r}")
    return value.upper()


class ThemeInfo(BaseModel):
    name: str
    version: str
    formats: list[Format]


class Colours(BaseModel):
    roles: dict[str, str]
    chart: dict[str, list[str]]
    usage: dict[Literal["text", "fill", "stroke"], list[str]]
    contrast_min: float

    @field_validator("roles", mode="before")
    @classmethod
    def _roles(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {name: to_colour(colour) for name, colour in value.items()}
        return value

    @field_validator("chart", mode="before")
    @classmethod
    def _chart(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {name: [to_colour(colour) for colour in colours] for name, colours in value.items()}
        return value


class Family(BaseModel):
    name: str
    files: list[str]


class TypeRole(BaseModel):
    family: str
    size: float
    weight: int = 400
    leading: float | None = None


class TypeScale(BaseModel):
    roles: dict[str, TypeRole]
    min_size: float

    @model_validator(mode="before")
    @classmethod
    def _from_mapping(cls, value: Any) -> Any:
        if isinstance(value, dict) and "roles" not in value:
            roles = {key: role for key, role in value.items() if key != "min_size"}
            return {"roles": roles, "min_size": value.get("min_size")}
        return value


class Margins(BaseModel):
    top: Length
    right: Length
    bottom: Length
    left: Length


class Page(BaseModel):
    width: Length
    height: Length
    margin: Margins
    columns: int = 1
    gutter: Length = 0

    @model_validator(mode="before")
    @classmethod
    def _named_size(cls, value: Any) -> Any:
        if isinstance(value, dict) and "size" in value:
            size = value["size"]
            if size not in PAGE_SIZES:
                raise ValueError(f"unknown page size: {size!r}")
            width, height = PAGE_SIZES[size]
            rest = {key: item for key, item in value.items() if key != "size"}
            return {"width": width, "height": height, **rest}
        return value


class TypeTokens(BaseModel):
    families: dict[str, Family]
    scale: dict[Format, TypeScale]


class Spacing(BaseModel):
    unit: float
    scale: list[float]


class Imagery(BaseModel):
    min_dpi: float


class Tokens(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: int = Field(alias="schema")
    colour: Colours
    type: TypeTokens
    pages: dict[Format, Page]
    spacing: Spacing
    imagery: Imagery | None = None


class Theme(BaseModel):
    root: Path
    info: ThemeInfo
    tokens: Tokens

    @property
    def fonts_dir(self) -> Path:
        return self.root / "fonts"
