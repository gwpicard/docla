"""Export the version manifest schema."""

import argparse
import json
from pathlib import Path

from docla.store import Manifest


def export_manifest_schema(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "Manifest.schema.json"
    path.write_text(
        json.dumps(Manifest.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    export_manifest_schema(parser.parse_args().directory)


if __name__ == "__main__":
    main()
