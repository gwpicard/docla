"""Evaluate critic verdicts against labelled crops."""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, cast

import yaml  # type: ignore[import-untyped]
from PIL import Image, ImageChops
from pydantic import BaseModel

from docla.agents.critic import PRECISION_MIN
from docla.facts.sheets import contact_sheet

MUTATIONS = {"cramped": "sem.focal-point", "off-balance": "sem.balance", "repeated": "sem.repetition"}
Answer = Literal["pass", "fail", "unsure"]


def mutate(png: Path, kind: str, out: Path) -> Path:
    if kind not in MUTATIONS:
        raise ValueError(f"Unknown mutation: {kind}")
    if kind == "repeated":
        return contact_sheet([png] * 4, ["1", "2", "3", "4"], out)
    with Image.open(png) as source:
        image = source.convert("RGB")
    background = image.getpixel((0, 0))
    canvas = Image.new("RGB", image.size, background)
    box = ImageChops.difference(image, canvas).getbbox()
    if box:
        content = image.crop(box)
        margin_x, margin_y = round(image.width * 0.02), round(image.height * 0.02)
        if kind == "cramped":
            content = content.resize(
                (image.width - 2 * margin_x, image.height - 2 * margin_y), Image.Resampling.LANCZOS
            )
            canvas.paste(content, (margin_x, margin_y))
        else:
            canvas.paste(content, (margin_x, box[1]))
    canvas.save(out, format="PNG")
    return out


class CriticCase(BaseModel):
    id: str
    crop: Path
    rubric_id: str
    verdict: Literal["pass", "fail"]


def load_cases(folder: Path) -> list[CriticCase]:
    entries = yaml.safe_load((folder / "labels.yaml").read_text())["cases"]
    cases = [CriticCase(**(entry | {"crop": folder / entry["crop"]})) for entry in entries]
    for case in cases:
        if not case.crop.is_file():
            raise ValueError(f"Missing crop: {case.crop}")
    return cases


Verdict = Callable[[CriticCase, int], Awaitable[Answer]]


class ScriptedCritic:
    async def __call__(self, case: CriticCase, run: int) -> Answer:
        return case.verdict


class ItemResult(BaseModel):
    labelled: int
    tp: int
    fp: int
    fn: int
    precision: float | None
    recall: float | None
    agreement: float | None


class CriticEvalReport(BaseModel):
    mode: Literal["offline", "live"] = "offline"
    cases: int
    runs: int
    agreed: int
    items: dict[str, ItemResult]


async def run_critic(cases: list[CriticCase], verdict: Verdict, *, runs: int = 2) -> CriticEvalReport:
    if runs != 2:
        raise ValueError("Critic evaluation requires two runs")
    grouped: dict[str, list[tuple[CriticCase, list[Answer]]]] = {}
    for case in cases:
        answers = [await verdict(case, number) for number in range(1, runs + 1)]
        grouped.setdefault(case.rubric_id, []).append((case, answers))
    results = {}
    agreed = 0
    for item, rows in grouped.items():
        tp = sum(answer == "fail" and case.verdict == "fail" for case, answers in rows for answer in answers)
        fp = sum(answer == "fail" and case.verdict == "pass" for case, answers in rows for answer in answers)
        fn = sum(answer != "fail" and case.verdict == "fail" for case, answers in rows for answer in answers)
        same = sum(answers[0] == answers[1] for _, answers in rows)
        agreed += same
        results[item] = ItemResult(
            labelled=len(rows),
            tp=tp,
            fp=fp,
            fn=fn,
            precision=tp / (tp + fp) if tp + fp else None,
            recall=tp / (tp + fn) if tp + fn else None,
            agreement=same / len(rows),
        )
    return CriticEvalReport(cases=len(cases), runs=runs, agreed=agreed, items=results)


def render_results(report: CriticEvalReport) -> str:
    pct = 100 * report.agreed / report.cases if report.cases else 0
    lines = [
        "# Critic eval",
        "",
        f"Mode: {report.mode}",
        f"Cases: {report.cases}",
        f"Runs: {report.runs}",
        f"Agreement: {report.agreed} / {report.cases} ({pct:.1f}%)",
        "",
        "| Item | Labelled | Precision | Recall | Agreement | Actionable |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    def fmt(value: float | None) -> str:
        return "-" if value is None else f"{value:.2f}"

    for item, row in sorted(report.items.items()):
        action = "yes" if row.precision is not None and row.precision >= PRECISION_MIN else "no"
        lines.append(
            f"| {item} | {row.labelled} | {fmt(row.precision)} | {fmt(row.recall)} | {fmt(row.agreement)} | {action} |"
        )
    return "\n".join(lines) + "\n"


def calibration_yaml(report: CriticEvalReport) -> str:
    items = {
        item: {"precision": row.precision, "recall": row.recall, "agreement": row.agreement, "n": row.labelled}
        for item, row in sorted(report.items.items())
        if row.precision is not None
    }
    return f"# docla eval critic, mode: {report.mode}\n" + cast(str, yaml.safe_dump({"items": items}, sort_keys=False))
