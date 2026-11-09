"""Gather facts from source spans cited by Claude."""

import base64
import re
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from docla.agents.client import Claude
from docla.agents.prompts import system_blocks
from docla.sources import Extracted

MAX_CHUNK_CHARS = 100_000
MAX_PDF_PAGES = 100


class Fact(BaseModel):
    text: str
    source_key: str
    locator: str | None = None


def _chunks(source: Extracted) -> Iterator[tuple[int, dict[str, Any]]]:
    if source.kind == "pdf" and source.pages is not None and source.pages <= MAX_PDF_PAGES:
        yield (
            0,
            {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(source.source.read_bytes()).decode("ascii"),
            },
        )
        return
    offset = 0
    while offset < len(source.text):
        end = min(offset + MAX_CHUNK_CHARS, len(source.text))
        if end < len(source.text):
            newline = source.text.rfind("\n", offset, end)
            if newline >= offset:
                end = newline + 1
        yield offset, {"type": "text", "media_type": "text/plain", "data": source.text[offset:end]}
        offset = end


def _locator(source: Extracted, citation: dict[str, Any], offset: int) -> str | None:
    if citation["type"] == "page_location":
        return f"p.{citation['start_page_number']}"
    position = offset + citation["start_char_index"]
    pattern = r"^\[(\d{2}:\d{2}(?::\d{2})?)\]" if source.kind == "vtt" else r"<!-- page (\d+) -->"
    matches = [match for match in re.finditer(pattern, source.text, re.MULTILINE) if match.start() <= position]
    if not matches:
        return None
    value = matches[-1].group(1)
    return value if source.kind == "vtt" else f"p.{value}"


def _facts(source: Extracted, response: dict[str, Any], offset: int) -> Iterator[Fact]:
    for block in response.get("content", []):
        if block.get("type") != "text":
            continue
        for citation in block.get("citations") or []:
            if citation.get("type") not in {"char_location", "page_location"}:
                continue
            text = " ".join(citation["cited_text"].split())
            if text:
                yield Fact(text=text, source_key=source.key, locator=_locator(source, citation, offset))


async def gather(claude: Claude, extracted: list[Extracted]) -> list[Fact]:
    facts: list[Fact] = []
    seen: set[tuple[str, str, str | None]] = set()
    for source in extracted:
        if not source.text:
            continue
        for offset, data in _chunks(source):
            document = {
                "type": "document",
                "source": data,
                "title": f"{source.key} {source.name}",
                "citations": {"enabled": True},
            }
            content: list[dict[str, Any]] = [
                document,
                {
                    "type": "text",
                    "text": "State every usable fact, including numbers, dates, names and findings, with a citation.",
                },
            ]
            response = await claude.cite("gatherer", system=system_blocks("gatherer"), content=content)
            for fact in _facts(source, response, offset):
                key = (fact.text, fact.source_key, fact.locator)
                if key not in seen:
                    seen.add(key)
                    facts.append(fact)
    return facts
