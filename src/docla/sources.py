"""Extract project source files into stable plain text."""

import re
from pathlib import Path
from typing import Literal

import pdfplumber
from pydantic import BaseModel


class Extracted(BaseModel):
    key: str
    name: str
    kind: Literal["pdf", "text", "vtt", "table"]
    source: Path
    path: Path
    text: str
    pages: int | None = None


def _pdf(source: Path) -> tuple[str, int]:
    with pdfplumber.open(source) as pdf:
        blocks = [
            f"<!-- page {number} -->\n{(page.extract_text() or '').rstrip()}"
            for number, page in enumerate(pdf.pages, 1)
        ]
        return "\n\n".join(blocks), len(pdf.pages)


def _timestamp(value: str) -> str:
    parts = value.split(".", 1)[0].split(":")
    if len(parts) == 3 and int(parts[0]) == 0:
        parts = parts[1:]
    return ":".join(parts)


def _cue(block: str) -> str | None:
    lines = block.splitlines()
    if not lines or re.match(r"^(?:WEBVTT|NOTE|STYLE|REGION)(?:\s|$)", lines[0]):
        return None
    timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
    if timing is None:
        return None
    start = lines[timing].split("-->", 1)[0].strip()
    content = " ".join(lines[timing + 1 :])
    content = re.sub(r"<v(?:\.[^\s>]*)?\s+([^>]+)>", r"\1: ", content)
    content = re.sub(r"<[^>]*>", "", content)
    return f"[{_timestamp(start)}] {content}"


def _vtt(source: Path) -> str:
    content = source.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", content)
    return "\n".join(cue for block in blocks if (cue := _cue(block)) is not None)


def source_files(project: Path) -> list[Path]:
    source_dir = project / "sources"
    if not source_dir.exists():
        return []
    return sorted(
        path
        for path in source_dir.iterdir()
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in {".pdf", ".txt", ".md", ".vtt", ".xlsx", ".csv"}
    )


def extract(project: Path) -> list[Extracted]:
    sources = source_files(project)
    results = []
    for number, source in enumerate(sources, 1):
        suffix = source.suffix.lower()
        pages = None
        kind: Literal["pdf", "text", "vtt", "table"]
        if suffix == ".pdf":
            kind = "pdf"
            content, pages = _pdf(source)
        elif suffix == ".vtt":
            kind = "vtt"
            content = _vtt(source)
        elif suffix in {".xlsx", ".csv"}:
            from docla.tables import table_facts

            kind = "table"
            content = "\n".join(f"[{fact.locator}] {fact.text}" for fact in table_facts(source, f"S{number}"))
        else:
            kind = "text"
            content = source.read_text(encoding="utf-8")
        content = content.rstrip("\n") + "\n"
        path = project / "extracted" / (source.name + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
        results.append(
            Extracted(
                key=f"S{number}",
                name=source.name,
                kind=kind,
                source=source,
                path=path,
                text=content,
                pages=pages,
            )
        )
    return results
