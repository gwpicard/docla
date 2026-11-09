"""Generate labelled synthetic failures from PNG crops."""

import sys
from pathlib import Path

import yaml

from docla.evals.critic import MUTATIONS, mutate


def main() -> None:
    source, out = map(Path, sys.argv[1:])
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for png in sorted(source.glob("*.png")):
        for kind, item in MUTATIONS.items():
            name = f"{png.stem}-{kind}"
            mutate(png, kind, out / f"{name}.png")
            cases.append({"id": name, "crop": f"{name}.png", "rubric_id": item, "verdict": "fail"})
    (out / "mutations.yaml").write_text(yaml.safe_dump({"cases": cases}, sort_keys=False))


if __name__ == "__main__":
    main()
