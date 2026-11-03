import json
import random
from collections.abc import Iterable
from pathlib import Path

from doclo.model import Document

ID_LENGTH = 5
ID_SPACE = 16**ID_LENGTH


class IdStoreError(Exception):
    pass


def _read_issued(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise IdStoreError(f"cannot read id store {path}: {error}") from error
    issued = data.get("issued") if isinstance(data, dict) else None
    if not isinstance(issued, list) or not all(isinstance(i, str) for i in issued):
        raise IdStoreError(f"id store {path} must be an object with an 'issued' list of strings")
    return set(issued)


class IdStore:
    def __init__(self, path: Path, rng: random.Random | None = None):
        self.path = Path(path)
        self.rng = rng if rng is not None else random.Random()
        self.issued = _read_issued(self.path)

    def allocate(self, existing: Iterable[str] = ()) -> str:
        taken = set(existing) | self.issued
        if len(taken) >= ID_SPACE:
            raise IdStoreError(f"no ids left to issue in {self.path}")
        while True:
            candidate = f"{self.rng.randrange(ID_SPACE):0{ID_LENGTH}x}"
            if candidate not in taken:
                self.issued.add(candidate)
                return candidate

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"issued": sorted(self.issued)}, indent=2) + "\n"
        with self.path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)


def stamp(doc: Document, store: IdStore) -> tuple[Document, list[str]]:
    result = doc.model_copy(deep=True)
    present = {s.id for s in result.sections if s.id is not None}
    new_ids: list[str] = []
    for section in result.sections:
        if section.id is None:
            section.id = store.allocate(existing=present)
            present.add(section.id)
            new_ids.append(section.id)
    return result, new_ids
