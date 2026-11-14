"""Record missing materials and the identity described by guidelines."""

import json
import re
from pathlib import Path
from typing import Literal

import pdfplumber
from pydantic import BaseModel

from docla.brand.intake import MANIFEST, Manifest
from docla.brand.questions import BrandQuestion, QuestionSource, add_questions, drop_open_questions, load_questions
from docla.brand.workspace import BrandError
from docla.model.source import Format

GapKind = Literal[
    "no-guidelines",
    "no-slide-template",
    "no-word-template",
    "no-slide-examples",
    "no-doc-examples",
    "no-logo",
    "no-fonts",
]


class Gap(BaseModel):
    kind: GapKind
    format: Format | None
    message: str


class Identity(BaseModel):
    file: str
    version: str | None
    date: str | None
    page: int | None
    quote: str | None


def find_gaps(manifest: Manifest) -> list[Gap]:
    files = [entry for entry in manifest.files if entry.unread is None]
    checks: list[tuple[GapKind, Format | None, str, bool]] = [
        ("no-guidelines", None, "guidelines PDF", any(e.role == "guidelines" and e.type == "pdf" for e in files)),
        (
            "no-slide-template",
            "slides",
            "slide template",
            any(e.role == "templates" and e.type in ("pptx", "potx") for e in files),
        ),
        (
            "no-word-template",
            "doc",
            "Word template",
            any(e.role == "templates" and e.type in ("docx", "dotx") for e in files),
        ),
        (
            "no-slide-examples",
            "slides",
            "slide examples",
            any(e.role == "examples" and e.format == "slides" for e in files),
        ),
        ("no-doc-examples", "doc", "document examples", any(e.role == "examples" and e.format == "doc" for e in files)),
        ("no-logo", None, "logo", any(e.role == "logos" and e.type in ("svg", "png", "jpg") for e in files)),
        ("no-fonts", None, "fonts", any(e.role == "fonts" and e.type in ("ttf", "otf") for e in files)),
    ]
    return [
        Gap(kind=kind, format=fmt, message=f"No {name} supplied.") for kind, fmt, name, present in checks if not present
    ]


_VERSION = re.compile(r"\b(?:version|v)\s*(\d+(?:\.\d+)*)\b", re.IGNORECASE)
_DATE = re.compile(
    r"\b(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}|\d{4}-\d{2}(?:-\d{2})?)\b",
    re.IGNORECASE,
)


def _identity(brand: Path, file: str) -> Identity:
    version = date = None
    version_location: tuple[int, int, str] | None = None
    date_location: tuple[int, int, str] | None = None
    with pdfplumber.open(brand / file) as pdf:
        for page_number, page in enumerate(pdf.pages[:3], 1):
            for index, line in enumerate((page.extract_text() or "").splitlines()):
                if version is None and (match := _VERSION.search(line)):
                    version, version_location = match.group(1), (page_number, index, line)
                if date is None and (match := _DATE.search(line)):
                    date, date_location = match.group(), (page_number, index, line)
    found = [location for location in (version_location, date_location) if location is not None]
    first = min(found) if found else None
    return Identity(
        file=file,
        version=version,
        date=date,
        page=first[0] if first else None,
        quote=first[2] if first else None,
    )


def read_identity(brand: Path, manifest: Manifest) -> list[Identity]:
    paths = sorted(e.path for e in manifest.files if e.role == "guidelines" and e.type == "pdf" and e.unread is None)
    return [_identity(brand, path) for path in paths]


def gap_questions(gaps: list[Gap], identities: list[Identity]) -> list[BrandQuestion]:
    questions = [
        BrandQuestion(
            id=f"gap.{gap.kind}",
            kind="gap",
            format=gap.format,
            blocking=False,
            text=f"{gap.message} Will you supply it or record that the brand has none?",
        )
        for gap in gaps
    ]
    if identities:
        missing_source = QuestionSource(file=identities[0].file)
        for field in ("version", "date"):
            if not any(getattr(identity, field) for identity in identities):
                questions.append(
                    BrandQuestion(
                        id=f"identity.{field}",
                        kind="identity",
                        blocking=False,
                        text=f"What is the guidelines' {field}?",
                        source=missing_source,
                    )
                )
    identity = next((i for i in identities if i.version or i.date), None)
    details = (
        []
        if identity is None
        else ([f"version {identity.version}"] if identity.version else []) + ([identity.date] if identity.date else [])
    )
    context = f" The guidelines state {' and '.join(details)}." if details else ""
    source = QuestionSource(file=identity.file, page=identity.page, quote=identity.quote) if identity else None
    questions.append(
        BrandQuestion(
            id="identity.earlier",
            kind="identity",
            blocking=True,
            source=source,
            text=f"Do any materials use an earlier identity of the brand, and which files?{context}",
        )
    )
    return questions


def check_gaps(brand: Path) -> tuple[list[Gap], list[Identity]]:
    path = brand / MANIFEST
    if not path.exists():
        raise BrandError("Run docla brand intake first")
    manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    gaps = find_gaps(manifest)
    identities = read_identity(brand, manifest)
    wanted = gap_questions(gaps, identities)
    add_questions(brand, wanted)
    current = {question.id for question in wanted}
    stale = [q.id for q in load_questions(brand) if q.id.startswith(("gap.", "identity.")) and q.id not in current]
    drop_open_questions(brand, stale)
    report = {"gaps": [g.model_dump() for g in gaps], "identity": [i.model_dump() for i in identities]}
    (brand / "theme/ingest/gaps.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return gaps, identities
