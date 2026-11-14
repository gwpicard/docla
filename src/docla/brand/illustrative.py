"""Identify sample-based claims and ask the owner about them."""

from typing import Literal

from docla.brand.claims import Claim, VerifiedSource
from docla.brand.pages import PageEntry, PageIndex
from docla.brand.questions import BrandQuestion, QuestionOption, QuestionSource
from docla.facts.models import FactBox


def _overlaps_image(source: VerifiedSource, page: PageEntry) -> bool:
    box = source.bbox
    if box is None or len(box) != 4:
        return False
    x0, y0, x1, y1 = box
    area = (x1 - x0) * (y1 - y0)
    if x1 <= x0 or y1 <= y0:
        return False

    def overlap(image: FactBox) -> float:
        return max(0, min(x1, image.x1) - max(x0, image.x0)) * max(0, min(y1, image.y1) - max(y0, image.y0))

    return any(overlap(image.box) >= area / 2 for image in page.images)


def _image_only(claim: Claim, pages: dict[tuple[str, int], PageEntry]) -> bool:
    return bool(claim.sources) and all(
        source.found == "visual"
        and (page := pages.get((source.file, source.page))) is not None
        and _overlaps_image(source, page)
        for source in claim.sources
    )


def mark_illustrative(claims: list[Claim], index: PageIndex) -> list[Claim]:
    pages = {(page.file, page.page): page for page in index.pages}
    marked = []
    for claim in claims:
        reason: Literal["shown", "image"] | None = None
        if claim.basis == "shown":
            reason = "shown"
        elif _image_only(claim, pages):
            reason = "image"
        updates: dict[str, object] = {"illustrative": reason is not None, "illustrative_reason": reason}
        if reason is not None:
            updates["strength"] = "soft"
        marked.append(claim.model_copy(update=updates))
    return marked


def illustrative_questions(claims: list[Claim]) -> list[BrandQuestion]:
    questions = []
    for claim in claims:
        if not claim.illustrative:
            continue
        source = claim.sources[0]
        questions.append(
            BrandQuestion(
                id=f"claim.illustrative.{claim.id}",
                kind="illustrative",
                blocking=False,
                source=QuestionSource(file=source.file, page=source.page, quote=source.quote),
                format=claim.formats[0] if len(claim.formats) == 1 else None,
                text=(
                    f'Page {source.page} of {source.file} shows: "{claim.statement}" '
                    "Is this a rule, or only an example?"
                ),
                options=[
                    QuestionOption(id="rule", label="Make it a rule"),
                    QuestionOption(id="example", label="Only an example"),
                ],
                recommended="example",
            )
        )
    return questions
