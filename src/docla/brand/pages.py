"""Index PDF pages and their reproducible visual evidence."""

import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Literal

import pdfplumber
from pydantic import BaseModel

from docla.brand.intake import MANIFEST, Manifest, MaterialEntry, Role
from docla.brand.workspace import BrandError
from docla.facts.models import ImageFact, PageFacts
from docla.facts.pdf import PdfPlumberFacts
from docla.facts.raster import PdfiumRasteriser
from docla.model.source import Format

PAGES = Path("theme/ingest/pages.json")
WORK = Path("theme/ingest/work")
PAGE_SCALE = 110 / 72


class FontUse(BaseModel):
    name: str
    size: float
    words: int


class ColourUse(BaseModel):
    hex: str
    use: Literal["text", "fill", "stroke"]
    count: int


class PageEntry(BaseModel):
    file: str
    sha256: str
    role: Role
    page: int
    format: Format
    width: float
    height: float
    text: str
    fonts: list[FontUse]
    colours: list[ColourUse]
    images: list[ImageFact]
    png: str


class SkippedFile(BaseModel):
    file: str
    reason: str


class PageIndex(BaseModel):
    schema_version: int = 1
    pages: list[PageEntry]
    skipped: list[SkippedFile]


def material_key(path: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", path.removeprefix("materials/").lower())


def load_manifest(brand: Path) -> Manifest:
    path = brand / MANIFEST
    if not path.exists():
        raise BrandError("Run docla brand intake first")
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def _fonts(facts: PageFacts) -> list[FontUse]:
    counts = Counter((re.sub(r"^[A-Z]{6}\+", "", word.font), round(word.size, 1)) for word in facts.words)
    return [
        FontUse(name=name, size=size, words=count)
        for (name, size), count in sorted(counts.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
    ]


def _colours(facts: PageFacts) -> list[ColourUse]:
    counts: Counter[tuple[Literal["text", "fill", "stroke"], str]] = Counter()
    counts.update(("text", word.colour) for word in facts.words if word.colour is not None)
    for shape in facts.shapes:
        if shape.fill is not None:
            counts[("fill", shape.fill)] += 1
        if shape.stroke is not None:
            counts[("stroke", shape.stroke)] += 1
    return [
        ColourUse(use=use, hex=colour, count=count)
        for (use, colour), count in sorted(counts.items(), key=lambda item: (item[0][0], -item[1], item[0][1]))
    ]


def _parse_file(brand: Path, entry: MaterialEntry) -> list[PageEntry]:
    path = brand / entry.path
    facts = PdfPlumberFacts().extract(path)
    with pdfplumber.open(path) as pdf:
        texts = [page.extract_text() or "" for page in pdf.pages]
    folder = brand / WORK / "pages" / material_key(entry.path)
    if folder.exists():
        shutil.rmtree(folder)
    images = PdfiumRasteriser().render(path, folder, scale=PAGE_SCALE)
    return [
        PageEntry(
            file=entry.path,
            sha256=entry.sha256,
            role=entry.role,
            page=page.page,
            format="slides" if page.width > page.height else "doc",
            width=page.width,
            height=page.height,
            text=text,
            fonts=_fonts(page),
            colours=_colours(page),
            images=page.images,
            png=image.relative_to(brand).as_posix(),
        )
        for page, text, image in zip(facts, texts, images, strict=True)
    ]


def _ignore_work(brand: Path) -> None:
    path = brand / ".gitignore"
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    line = "theme/ingest/work/"
    if line not in content.splitlines():
        path.write_text(
            content + ("\n" if content and not content.endswith("\n") else "") + line + "\n", encoding="utf-8"
        )


def parse_pdfs(brand: Path) -> PageIndex:
    manifest = load_manifest(brand)
    pages: list[PageEntry] = []
    skipped: list[SkippedFile] = []
    for entry in manifest.files:
        if entry.type == "pdf" and entry.unread is None:
            try:
                pages.extend(_parse_file(brand, entry))
            except Exception as error:
                skipped.append(SkippedFile(file=entry.path, reason=str(error)))
    index = PageIndex(pages=sorted(pages, key=lambda page: (page.file, page.page)), skipped=skipped)
    _ignore_work(brand)
    destination = brand / PAGES
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(index.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return index


def load_pages(brand: Path) -> PageIndex:
    path = brand / PAGES
    if not path.exists():
        raise BrandError("Run docla brand parse first")
    return PageIndex.model_validate_json(path.read_text(encoding="utf-8"))
