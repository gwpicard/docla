from typing import Literal

from pydantic import BaseModel

# All lengths are in pt with the origin at the top left of the page; pages count from 1.

ShapeKind = Literal["rect", "line", "curve"]


class FactBox(BaseModel):
    page: int
    x0: float
    y0: float
    x1: float
    y1: float


class Word(BaseModel):
    text: str
    font: str
    size: float
    colour: str | None
    box: FactBox
    baseline: float


class Shape(BaseModel):
    kind: ShapeKind
    fill: str | None
    stroke: str | None
    box: FactBox


class PageFacts(BaseModel):
    page: int
    width: float
    height: float
    words: list[Word]
    shapes: list[Shape]
