import hashlib
from pathlib import Path

from pydantic import BaseModel

from docla.facts.models import FactBox, PageFacts, Shape, Word
from docla.facts.pdf import PdfFacts, PdfPlumberFacts
from docla.render.marks import ElementMark, Mark, SectionMark, read_marks

Point = tuple[int, float, float]


class PlacedWord(Word):
    role: str | None
    section_id: str | None


class PlacedShape(Shape):
    role: str | None
    section_id: str | None


class LayoutFacts(BaseModel):
    pdf_sha256: str
    pages: list[PageFacts]
    words: list[PlacedWord]
    shapes: list[PlacedShape]
    marks: list[Mark]


def centre(box: FactBox) -> Point:
    return (box.page, (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)


def contains(mark: ElementMark, point: Point) -> bool:
    page, x, y = point
    return mark.page == page and mark.x <= x <= mark.x + mark.w and mark.y <= y <= mark.y + mark.h


def _innermost(elements: list[ElementMark], point: Point) -> ElementMark | None:
    containing = [mark for mark in elements if contains(mark, point)]
    return min(containing, key=lambda mark: mark.w * mark.h, default=None)


def _section(starts: list[SectionMark], ends: dict[str, SectionMark], point: Point) -> str | None:
    page, _, y = point
    before = [mark for mark in starts if (mark.page, mark.y) <= (page, y)]
    if not before:
        return None
    start = before[-1]
    end = ends.get(start.id)
    if end is not None and (end.page, end.y) < (page, y):
        return None
    return start.id


class _Placer:
    def __init__(self, marks: list[Mark]) -> None:
        sections = [mark for mark in marks if isinstance(mark, SectionMark)]
        self.elements = [mark for mark in marks if isinstance(mark, ElementMark)]
        self.starts = sorted((m for m in sections if m.edge == "start"), key=lambda m: (m.page, m.y, m.x))
        self.ends = {m.id: m for m in sections if m.edge == "end"}

    def place(self, box: FactBox) -> tuple[str | None, str | None]:
        """Return the role and section id of an item with this box."""
        point = centre(box)
        element = _innermost(self.elements, point)
        if element is not None:
            return element.role, element.id
        return None, _section(self.starts, self.ends, point)

    def word(self, word: Word) -> PlacedWord:
        role, section_id = self.place(word.box)
        return PlacedWord(**word.model_dump(), role=role, section_id=section_id)

    def shape(self, shape: Shape) -> PlacedShape:
        role, section_id = self.place(shape.box)
        return PlacedShape(**shape.model_dump(), role=role, section_id=section_id)


def join(pages: list[PageFacts], marks: list[Mark], pdf_sha256: str) -> LayoutFacts:
    placer = _Placer(marks)
    words = [placer.word(word) for page in pages for word in page.words]
    shapes = [placer.shape(shape) for page in pages for shape in page.shapes]
    return LayoutFacts(pdf_sha256=pdf_sha256, pages=pages, words=words, shapes=shapes, marks=marks)


def layout_facts(pdf: Path, main: Path, root: Path, extractor: PdfFacts | None = None) -> LayoutFacts:
    pages = (extractor or PdfPlumberFacts()).extract(pdf)
    marks = read_marks(main, root)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    return join(pages, marks, digest)
