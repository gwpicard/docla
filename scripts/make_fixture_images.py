"""Generate the image used by the image resolution fixture."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        root / "tests/fixtures/seeded-defects/source.image-resolves/pass/assets"
    )
    folder.mkdir(parents=True, exist_ok=True)
    picture = Image.new("RGB", (2000, 1125), "#dce8e8")
    draw = ImageDraw.Draw(picture)
    draw.ellipse((1400, 120, 1700, 420), fill="#f2d6a2")
    draw.polygon([(0, 850), (600, 350), (1150, 850)], fill="#6c9892")
    draw.polygon([(700, 1125), (1400, 400), (2000, 1000), (2000, 1125)], fill="#3e706d")
    picture.save(folder / "picture.png")


if __name__ == "__main__":
    main()
