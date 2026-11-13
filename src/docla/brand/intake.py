"""Record the materials supplied for a brand."""

import hashlib
import os
import re
import zipfile
from pathlib import Path
from typing import Literal, cast, get_args
from xml.etree import ElementTree

import pdfplumber
from pydantic import BaseModel

from docla.brand.workspace import MATERIAL_CLASSES
from docla.model.source import Format

Role = Literal["guidelines", "templates", "examples", "logos", "fonts", "notes", "unsorted"]
FileType = Literal[
    "pdf",
    "pptx",
    "potx",
    "docx",
    "dotx",
    "png",
    "jpg",
    "svg",
    "ttf",
    "otf",
    "woff",
    "woff2",
    "md",
    "txt",
    "yaml",
    "json",
    "xlsx",
    "csv",
    "other",
]
MANIFEST = Path("theme/ingest/manifest.json")


class MaterialEntry(BaseModel):
    path: str
    role: Role
    type: FileType
    sha256: str
    size: int
    pages: int | None
    format: Format | None
    unread: str | None = None


class Manifest(BaseModel):
    schema_version: int = 1
    brand: str
    files: list[MaterialEntry]


def material_files(brand: Path) -> list[Path]:
    paths = []
    for root, dirs, files in os.walk(brand / "materials"):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        paths.extend(Path(root) / name for name in files if not name.startswith("."))
    return sorted(path for path in paths if path.is_file())


def _file_type(path: Path) -> FileType:
    extension = path.suffix.lower().removeprefix(".")
    extension = {"jpeg": "jpg", "yml": "yaml"}.get(extension, extension)
    return cast(FileType, extension if extension in get_args(FileType) else "other")


def _pdf(path: Path) -> tuple[int | None, Format | None, str | None]:
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ValueError("Not a PDF")
        with pdfplumber.open(path) as pdf:
            page = pdf.pages[0]
            return len(pdf.pages), "slides" if page.width > page.height else "doc", None
    except Exception:
        return None, None, "Could not read this file as a PDF"


def _office(path: Path, kind: FileType) -> tuple[int | None, Format | None, str | None]:
    fmt: Format = "slides" if kind in ("pptx", "potx") else "doc"
    try:
        with zipfile.ZipFile(path) as archive:
            if fmt == "slides":
                return sum(bool(re.fullmatch(r"ppt/slides/slide\d+\.xml", n)) for n in archive.namelist()), fmt, None
            try:
                root = ElementTree.fromstring(archive.read("docProps/app.xml"))
                pages = next((node.text for node in root.iter() if node.tag.split("}")[-1] == "Pages"), None)
                return int(pages) if pages is not None else None, fmt, None
            except KeyError:
                return None, fmt, None
    except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return None, fmt, "Could not read this file as an Office archive"


def _unsupported(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in (".key", ".ppt", ".odp"):
        return "Please supply a PowerPoint or PDF export"
    if extension in (".doc", ".odt", ".rtf", ".pages"):
        return "Please supply a Word or PDF export"
    if extension == ".indd":
        return "Please supply a PDF export"
    return "This file type is not read"


def _entry(brand: Path, path: Path) -> MaterialEntry:
    relative = path.relative_to(brand)
    parts = relative.parts
    role = cast(Role, parts[1] if len(parts) > 2 and parts[1] in MATERIAL_CLASSES else "unsorted")
    kind = _file_type(path)
    data = path.read_bytes()
    pages: int | None = None
    fmt: Format | None = None
    unread = None
    if kind == "pdf":
        pages, fmt, unread = _pdf(path)
    elif kind in ("pptx", "potx", "docx", "dotx"):
        pages, fmt, unread = _office(path, kind)
    elif kind == "other":
        unread = _unsupported(path)
    return MaterialEntry(
        path=relative.as_posix(),
        role=role,
        type=kind,
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        pages=pages,
        format=fmt,
        unread=unread,
    )


def take_in(brand: Path) -> Manifest:
    manifest = Manifest(brand=brand.name, files=[_entry(brand, path) for path in material_files(brand)])
    destination = brand / MANIFEST
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest
