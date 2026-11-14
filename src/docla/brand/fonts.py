"""Measure and install supplied brand fonts."""

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from pydantic import BaseModel

from docla.brand.questions import BrandQuestion, QuestionSource

Embedding = Literal["installable", "restricted", "preview-print", "editable", "bitmap-only"]
FontStatus = Literal["ok", "mismatch", "unlabelled", "no-licence", "restricted", "unreadable", "unsupported"]
FONT_DIR = Path("materials/fonts")


class FontFile(BaseModel):
    file: str
    sha256: str
    family: str | None
    weight: int | None
    fs_type: int | None
    embedding: Embedding | None
    label_family: str | None
    label_weight: int | None
    licence: str | None
    status: FontStatus


class FontReport(BaseModel):
    files: list[FontFile]
    typefaces: dict[str, list[str]]
    questions: list[BrandQuestion]


def font_paths(brand: Path) -> list[Path]:
    folder = brand / FONT_DIR
    return sorted(
        p
        for p in folder.glob("*")
        if p.is_file()
        and not p.name.startswith(".")
        and p.name != "fonts.yaml"
        and p.suffix.lower() not in {".txt", ".md", ".pdf"}
    )


def _embedding(fs_type: int) -> Embedding:
    if fs_type & 0x0200:
        return "bitmap-only"
    if fs_type & 0x0008:
        return "editable"
    if fs_type & 0x0004:
        return "preview-print"
    if fs_type & 0x0002:
        return "restricted"
    return "installable"


def _measure(path: Path) -> tuple[str | None, int | None, int | None, Embedding | None]:
    with TTFont(path) as font:
        names = font["name"]
        family = names.getDebugName(16) or names.getDebugName(1)
        os2 = font["OS/2"]
        weight, fs_type = int(os2.usWeightClass), int(os2.fsType)
        return family, weight, fs_type, _embedding(fs_type)


def _status(
    path: Path,
    label: dict[str, Any] | None,
    family: str | None,
    weight: int | None,
    embedding: Embedding | None,
    readable: bool,
) -> FontStatus:
    if path.suffix.lower() not in {".ttf", ".otf"}:
        return "unsupported"
    if not readable:
        return "unreadable"
    if label is None:
        return "unlabelled"
    if (label.get("family") or "").casefold() != (family or "").casefold() or label.get("weight") != weight:
        return "mismatch"
    if not (label.get("licence") or "").strip():
        return "no-licence"
    if embedding in {"restricted", "bitmap-only"}:
        return "restricted"
    return "ok"


def _check_file(path: Path, label: dict[str, Any] | None) -> FontFile:
    family = weight = fs_type = embedding = None
    readable = False
    if path.suffix.lower() in {".ttf", ".otf"}:
        try:
            family, weight, fs_type, embedding = _measure(path)
            readable = True
        except Exception:
            pass
    details = label or {}
    return FontFile(
        file=path.name,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        family=family,
        weight=weight,
        fs_type=fs_type,
        embedding=embedding,
        label_family=details.get("family"),
        label_weight=details.get("weight"),
        licence=details.get("licence"),
        status=_status(path, label, family, weight, embedding, readable),
    )


def _file_question(font: FontFile) -> BrandQuestion:
    needs = {
        "unsupported": "supply a TTF or OTF file",
        "unreadable": "supply a readable font file",
        "unlabelled": "provide its family, weight and licence",
        "mismatch": "correct or confirm its label",
        "no-licence": "provide its licence",
        "restricted": "provide a font permitted for embedding",
    }
    text = f"{font.file} states family {font.family} and weight {font.weight}; please {needs[font.status]}."
    return BrandQuestion(
        id=f"font.{font.status}.{font.file}",
        kind="font",
        text=text,
        source=QuestionSource(file=(FONT_DIR / font.file).as_posix()),
    )


def check_fonts(brand: Path, typefaces: list[str] | None = None) -> FontReport:
    label_path = brand / FONT_DIR / "fonts.yaml"
    data = (yaml.safe_load(label_path.read_text(encoding="utf-8")) or {}) if label_path.exists() else {}
    labels = {item["file"]: item for item in data.get("fonts", [])}
    files = [_check_file(path, labels.get(path.name)) for path in font_paths(brand)]
    names = typefaces if typefaces is not None else data.get("typefaces", [])
    matches = {
        name: [f.file for f in files if f.status == "ok" and f.family and f.family.casefold() == name.casefold()]
        for name in names
    }
    questions = [
        BrandQuestion(
            id=f"font.missing.{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}",
            kind="font",
            text=f"Please supply the font files and licence for {name}.",
        )
        for name, found in matches.items()
        if not found
    ]
    questions.extend(_file_question(f) for f in files if f.status != "ok")
    return FontReport(files=files, typefaces=matches, questions=questions)


def install_fonts(brand: Path, report: FontReport) -> list[str]:
    target = brand / "theme/fonts"
    target.mkdir(parents=True, exist_ok=True)
    licence_path = target / "LICENSES.txt"
    records = licence_path.read_text(encoding="utf-8").strip().split("\n\n") if licence_path.exists() else []
    installed = []
    for font in report.files:
        if font.status != "ok":
            continue
        shutil.copyfile(brand / FONT_DIR / font.file, target / font.file)
        records = [r for r in records if f"file: {font.file}" not in r.splitlines()]
        keys = ("file", "family", "weight", "licence", "fs_type", "embedding", "sha256")
        values = {key: getattr(font, key) for key in keys}
        values["source"] = (FONT_DIR / font.file).as_posix()
        records.append("\n".join(f"{key}: {value}" for key, value in values.items()))
        installed.append(font.file)
    if records:
        licence_path.write_text("\n\n".join(records) + "\n", encoding="utf-8")
    return installed


def write_report(brand: Path, report: FontReport) -> None:
    path = brand / "theme/ingest/fonts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
