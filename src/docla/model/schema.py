import json
import sys
from pathlib import Path

from pydantic import BaseModel

from docla.model import Document, Finding, Patch, Rule

SCHEMA_MODELS: list[type[BaseModel]] = [Document, Finding, Patch, Rule]


def export_schemas(directory: Path) -> list[Path]:
    """Write one JSON Schema file per exported model and return the sorted paths."""
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for model in SCHEMA_MODELS:
        path = directory / f"{model.__name__}.schema.json"
        text = json.dumps(model.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path.write_bytes(text.encode("utf-8"))
        paths.append(path)
    return sorted(paths)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m docla.model.schema <directory>", file=sys.stderr)
        return 2
    directory = Path(argv[0])
    directory.mkdir(parents=True, exist_ok=True)
    export_schemas(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
