import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from docla.render.typst import TypstCompileError, typst_command, typst_env

MARK_QUERY = "query(<docla-mark>).map(it => it.value)"


class SectionMark(BaseModel):
    kind: Literal["section"]
    id: str
    edge: Literal["start", "end"]
    page: int
    x: float
    y: float


class ElementMark(BaseModel):
    kind: Literal["element"]
    role: str
    id: str
    page: int
    x: float
    y: float
    w: float
    h: float


class FitMark(BaseModel):
    kind: Literal["fit"]
    role: str
    id: str
    need: float
    have: float
    ok: bool


Mark = Annotated[SectionMark | ElementMark | FitMark, Field(discriminator="kind")]

_MARK_ADAPTER: TypeAdapter[Mark] = TypeAdapter(Mark)


class MarkError(ValueError):
    pass


def _validate_mark(index: int, raw: Any) -> Mark:
    try:
        return _MARK_ADAPTER.validate_python(raw)
    except ValidationError as error:
        raise MarkError(f"mark {index} is not valid: {error}") from error


def read_marks(main: Path, root: Path, font_paths: Sequence[Path] = ()) -> list[Mark]:
    command = [typst_command(), "eval", MARK_QUERY, "--in", str(main), "--root", str(root), "--ignore-system-fonts"]
    for path in font_paths:
        command += ["--font-path", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, env=typst_env())
    if result.returncode != 0:
        raise TypstCompileError(result.stderr)
    return [_validate_mark(index, raw) for index, raw in enumerate(json.loads(result.stdout))]
