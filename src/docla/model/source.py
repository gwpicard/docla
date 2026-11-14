from typing import Any, Literal

from pydantic import BaseModel, Field

Format = Literal["slides", "doc"]


class Source(BaseModel):
    key: str
    text: str


class Citation(BaseModel):
    key: str
    locator: str | None = None


class Item(BaseModel):
    head: str | None = None
    body: str
    sub: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class Section(BaseModel):
    id: str | None = None
    intent: str
    section: str | None = None
    component: str | None = None
    because: str | None = None
    owner: Literal["human", "ai"] | None = None
    lock: Literal["text", "all"] | None = None
    page: Literal["new"] | None = None
    span: Literal["column", "full"] | None = None
    redraft: str | None = None
    title: str | None = None
    items: list[Item] = Field(default_factory=list)
    paragraphs: list[str] = Field(default_factory=list)
    code: list[str] = Field(default_factory=list)
    note: str | None = None
    spoken: str | None = None
    source_line: str | None = None
    data: dict[str, Any] | None = None
    image: str | None = None
    icons: list[str] = Field(default_factory=list)
    extra_attrs: dict[str, str] = Field(default_factory=dict)


class Document(BaseModel):
    front: dict[str, Any]
    format: Format
    context: str = ""
    sources: list[Source] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    rev: int = 0
