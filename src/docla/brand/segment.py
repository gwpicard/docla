"""Sort guideline pages into topics for extraction."""

from importlib.resources import files
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel

from docla.agents.client import Claude
from docla.brand.agents import page_blocks
from docla.brand.pages import PageEntry, load_pages
from docla.brand.workspace import BrandError
from docla.model.source import Format

Topic = Literal[
    "colour",
    "typography",
    "grid-layout",
    "logo",
    "imagery",
    "iconography",
    "charts-data-viz",
    "voice-tone",
    "templates",
    "dos-donts",
    "legal-mandatory",
    "accessibility",
    "other",
]
TOPICS = Path("theme/ingest/topics.json")


class PageTopics(BaseModel):
    page: int
    topics: list[Topic]


class TopicReply(BaseModel):
    pages: list[PageTopics]


class TopicFile(BaseModel):
    file: str
    sha256: str
    formats: list[Format]
    pages: list[PageTopics]
    missing: list[int]


class TopicMap(BaseModel):
    schema_version: int = 1
    files: list[TopicFile]


def load_topics(brand: Path) -> TopicMap:
    path = brand / TOPICS
    if not path.exists():
        raise BrandError("Run docla brand segment first")
    return TopicMap.model_validate_json(path.read_text(encoding="utf-8"))


def _guidelines(brand: Path) -> dict[str, list[PageEntry]]:
    grouped: dict[str, list[PageEntry]] = {}
    for page in sorted(load_pages(brand).pages, key=lambda item: (item.file, item.page)):
        if page.role == "guidelines":
            grouped.setdefault(page.file, []).append(page)
    if not grouped:
        raise BrandError("No guidelines pages; run docla brand parse first")
    return grouped


def segment_needed(brand: Path) -> bool:
    grouped = _guidelines(brand)
    if not (brand / TOPICS).exists():
        return True
    existing = {entry.file: entry.sha256 for entry in load_topics(brand).files}
    return existing != {file: pages[0].sha256 for file, pages in grouped.items()}


async def _segment_file(brand: Path, claude: Claude, pages: list[PageEntry], batch_size: int) -> TopicFile:
    found: dict[int, set[Topic]] = {}
    prompt = files("docla.brand.prompts").joinpath("segment.txt").read_text(encoding="utf-8")
    for start in range(0, len(pages), batch_size):
        batch = pages[start : start + batch_size]
        content = [{"type": "text", "text": f"Pages of {pages[0].file}"}]
        for page in batch:
            content.extend(page_blocks(page, brand))
        reply = await claude.call(
            "brand.segment",
            TopicReply,
            system=[{"type": "text", "text": prompt}],
            content=content,
            effort="low",
            max_tokens=4000,
        )
        numbers = {page.page for page in batch}
        for item in reply.pages:
            if item.page in numbers:
                found.setdefault(item.page, set()).update(item.topics)
    return TopicFile(
        file=pages[0].file,
        sha256=pages[0].sha256,
        formats=sorted({page.format for page in pages}),
        pages=[
            PageTopics(page=page.page, topics=[topic for topic in get_args(Topic) if topic in found[page.page]])
            for page in pages
            if found.get(page.page)
        ],
        missing=[page.page for page in pages if not found.get(page.page)],
    )


async def segment_pages(brand: Path, claude: Claude, *, batch_size: int = 10) -> TopicMap:
    grouped = _guidelines(brand)
    for pages in grouped.values():
        for page in pages:
            if not (brand / page.png).is_file():
                raise BrandError("Page image missing; run docla brand parse first")
    old = {entry.file: entry for entry in load_topics(brand).files} if (brand / TOPICS).exists() else {}
    result: list[TopicFile] = []
    for file, pages in grouped.items():
        previous = old.get(file)
        if previous is not None and previous.sha256 == pages[0].sha256:
            result.append(previous)
        else:
            result.append(await _segment_file(brand, claude, pages, batch_size))
    topics = TopicMap(files=result)
    path = brand / TOPICS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(topics.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return topics


def topic_groups(topics: TopicMap) -> dict[Topic, list[tuple[str, int]]]:
    groups: dict[Topic, list[tuple[str, int]]] = {}
    for entry in topics.files:
        for page in entry.pages:
            for topic in page.topics:
                if topic != "other":
                    groups.setdefault(topic, []).append((entry.file, page.page))
    return groups
