"""Write the layout facts for a component fixture."""

import argparse
import json
from pathlib import Path

from docla.testing.golden import facts_for


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/components"))
    args = parser.parse_args()
    facts = facts_for(args.name, args.fixtures)
    (args.fixtures / f"{args.name}.facts.json").write_text(
        json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
