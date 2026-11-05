"""Build the slide component gallery with generated sample imagery."""

from pathlib import Path

from PIL import Image, ImageDraw

from docla import cli


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    slides = root / "tests" / "fixtures" / "slides"
    assets = slides / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    image = assets / "landscape.png"
    if not image.exists():
        picture = Image.new("RGB", (1200, 675), "#dce8e8")
        draw = ImageDraw.Draw(picture)
        draw.polygon([(0, 500), (350, 230), (650, 500)], fill="#6c9892")
        draw.polygon([(400, 675), (850, 260), (1200, 600), (1200, 675)], fill="#3e706d")
        picture.save(image)
    return cli.main(["build", str(slides / "gallery.md"), "--out", str(root / "build")])


if __name__ == "__main__":
    raise SystemExit(main())
