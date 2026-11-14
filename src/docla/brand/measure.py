"""Measure the distributions of example and guideline page geometry."""

import re
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Literal

from pydantic import BaseModel

from docla.brand.pages import load_pages
from docla.brand.segment import TOPICS, load_topics, topic_groups
from docla.brand.workspace import BrandError
from docla.checks.bounds import CAP_HEIGHT
from docla.facts.models import PageFacts, Word
from docla.facts.pdf import PdfFacts, PdfPlumberFacts
from docla.model.source import Format

MEASURE = Path("theme/ingest/measure.json")
Side = Literal["top", "right", "bottom", "left"]
Kind = Literal["examples", "layout-pages"]


class Stat(BaseModel):
    value: float
    min: float
    max: float
    n: int


class PageRef(BaseModel):
    file: str
    page: int


class ColourCount(BaseModel):
    hex: str
    count: int


class TitleLine(PageRef):
    text: str
    size: float


class PageMeasure(BaseModel):
    width: float
    height: float
    margin: dict[Side, float]
    title_size: float
    body_size: float
    smallest_size: float
    title_font: str | None
    body_font: str | None
    title_chars: int
    body_chars: int
    text_colours: dict[str, int]
    fill_colours: dict[str, int]
    words: int
    title: str


class MeasureSet(BaseModel):
    kind: Kind
    format: Format
    pages: list[PageRef]
    width: Stat
    height: Stat
    margin: dict[Side, Stat]
    title_size: Stat
    body_size: Stat
    smallest_size: Stat
    title_font: str | None
    body_font: str | None
    text_colours: list[ColourCount]
    fill_colours: list[ColourCount]
    words_per_page: Stat
    titles: list[TitleLine]


class SkippedPage(PageRef):
    reason: str


class Measurement(BaseModel):
    schema_version: int = 1
    sets: list[MeasureSet]
    skipped: list[SkippedPage]


def _font(words: list[Word], size: float) -> tuple[str | None, int]:
    counts: Counter[str] = Counter()
    for word in words:
        if word.size == size:
            counts[re.sub(r"^[A-Z]{6}\+", "", word.font)] += len(word.text)
    if not counts:
        return None, 0
    name = min(counts, key=lambda item: (-counts[item], item))
    return name, counts[name]


def measure_page(page: PageFacts) -> PageMeasure | None:
    boxes = [w.box.model_copy(update={"y0": w.baseline - CAP_HEIGHT * w.size, "y1": w.baseline}) for w in page.words]
    for box in [*(shape.box for shape in page.shapes), *(image.box for image in page.images)]:
        if (box.x1 - box.x0) * (box.y1 - box.y0) < 0.9 * page.width * page.height:
            boxes.append(box)
    if not boxes:
        return None
    sizes: Counter[float] = Counter()
    colours: Counter[str] = Counter()
    for word in page.words:
        sizes[word.size] += len(word.text)
        if word.colour is not None:
            colours[word.colour] += len(word.text)
    title_size = max(sizes, default=0.0)
    body_size = min(sizes, key=lambda size: (-sizes[size], size)) if sizes else 0.0
    title_font, title_chars = _font(page.words, title_size)
    body_font, body_chars = _font(page.words, body_size)
    title_words = [word for word in page.words if word.size == title_size]
    if title_words:
        top = min(word.baseline for word in title_words)
        title_words = sorted((word for word in title_words if word.baseline <= top + 1), key=lambda word: word.box.x0)
    return PageMeasure(
        width=page.width,
        height=page.height,
        margin={
            "top": min(b.y0 for b in boxes),
            "right": page.width - max(b.x1 for b in boxes),
            "bottom": page.height - max(b.y1 for b in boxes),
            "left": min(b.x0 for b in boxes),
        },
        title_size=title_size,
        body_size=body_size,
        smallest_size=min(sizes, default=0.0),
        title_font=title_font,
        body_font=body_font,
        title_chars=title_chars,
        body_chars=body_chars,
        text_colours=dict(colours),
        fill_colours=dict(Counter(s.fill for s in page.shapes if s.fill is not None)),
        words=len(page.words),
        title=" ".join(word.text for word in title_words),
    )


def _stat(values: list[float]) -> Stat:
    return Stat(value=round(median(values), 2), min=round(min(values), 2), max=round(max(values), 2), n=len(values))


def _counts(values: list[dict[str, int]]) -> list[ColourCount]:
    counts: Counter[str] = Counter()
    for value in values:
        counts.update(value)
    return [ColourCount(hex=name, count=count) for name, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


def _set_font(pages: list[PageMeasure], kind: Literal["title", "body"]) -> str | None:
    counts: Counter[str] = Counter()
    for page in pages:
        name = page.title_font if kind == "title" else page.body_font
        if name is not None:
            counts[name] += page.title_chars if kind == "title" else page.body_chars
    return min(counts, key=lambda name: (-counts[name], name)) if counts else None


def _make_set(kind: Kind, fmt: Format, items: list[tuple[PageRef, PageMeasure]]) -> MeasureSet:
    pages = [page for _, page in items]
    return MeasureSet(
        kind=kind,
        format=fmt,
        pages=[ref for ref, _ in items],
        width=_stat([p.width for p in pages]),
        height=_stat([p.height for p in pages]),
        margin={side: _stat([p.margin[side] for p in pages]) for side in ("top", "right", "bottom", "left")},
        title_size=_stat([p.title_size for p in pages]),
        body_size=_stat([p.body_size for p in pages]),
        smallest_size=_stat([p.smallest_size for p in pages]),
        title_font=_set_font(pages, "title"),
        body_font=_set_font(pages, "body"),
        text_colours=_counts([p.text_colours for p in pages]),
        fill_colours=_counts([p.fill_colours for p in pages]),
        words_per_page=_stat([p.words for p in pages]),
        titles=[
            TitleLine(file=ref.file, page=ref.page, text=p.title, size=p.title_size) for ref, p in items if p.title
        ],
    )


def _layout_refs(brand: Path) -> set[tuple[str, int]]:
    if not (brand / TOPICS).exists():
        return set()
    groups = topic_groups(load_topics(brand))
    return set(groups.get("grid-layout", []) + groups.get("templates", []))


def _collect(brand: Path, layout_pages: list[PageRef] | None, extractor: PdfFacts) -> Measurement:
    entries = sorted(load_pages(brand).pages, key=lambda p: (p.file, p.page))
    refs = _layout_refs(brand) if layout_pages is None else {(p.file, p.page) for p in layout_pages}
    slide_aspects = [p.width / p.height for p in entries if p.role == "examples" and p.format == "slides"]
    aspects = {"slides": median(slide_aspects) if slide_aspects else 16 / 9, "doc": 1 / 1.4142}
    cache: dict[str, dict[int, PageFacts]] = {}
    groups: dict[tuple[Kind, Format], list[tuple[PageRef, PageMeasure]]] = {}
    skipped: list[SkippedPage] = []
    for entry in entries:
        kind: Kind
        if entry.role == "examples":
            kind = "examples"
        elif (entry.file, entry.page) in refs:
            kind = "layout-pages"
        else:
            continue
        ref = PageRef(file=entry.file, page=entry.page)
        if kind == "layout-pages" and abs(entry.width / entry.height / aspects[entry.format] - 1) > 0.02:
            skipped.append(
                SkippedPage(**ref.model_dump(), reason="shows a layout at reduced scale; compared in calibration")
            )
            continue
        if entry.file not in cache:
            cache[entry.file] = {page.page: page for page in extractor.extract(brand / entry.file)}
        measured = measure_page(cache[entry.file][entry.page])
        if measured is None:
            skipped.append(SkippedPage(**ref.model_dump(), reason="no content"))
        else:
            groups.setdefault((kind, entry.format), []).append((ref, measured))
    return Measurement(sets=[_make_set(kind, fmt, groups[kind, fmt]) for kind, fmt in sorted(groups)], skipped=skipped)


def measure_brand(
    brand: Path, *, layout_pages: list[PageRef] | None = None, extractor: PdfFacts | None = None
) -> Measurement:
    result = _collect(brand, layout_pages, extractor or PdfPlumberFacts())
    path = brand / MEASURE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def load_measurement(brand: Path) -> Measurement:
    path = brand / MEASURE
    if not path.exists():
        raise BrandError("Run docla brand measure first")
    return Measurement.model_validate_json(path.read_text(encoding="utf-8"))
