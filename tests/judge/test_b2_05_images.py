# Intent: Resolve section images and copy them into the render kit under content-addressed names.
import hashlib
import inspect
import json

import pytest
from PIL import Image

from docla.model import Document, Section

try:
    import docla.render.compose as compose_module
except ImportError as error:
    if error.name != "docla.render.compose" and not str(error.name).startswith("docla.render.compose."):
        raise
    compose_module = None


def _interface():
    assert compose_module is not None, "docla.render.compose must exist"
    for name in ("compose", "assemble", "ComposeError"):
        assert hasattr(compose_module, name), f"docla.render.compose.{name} must exist"
    assert "assets" in inspect.signature(compose_module.compose).parameters, "compose must accept assets"
    return compose_module


def _document(*images):
    return Document(
        front={}, format="slides",
        sections=[Section(id=f"s{i}", intent="statement", image=image) for i, image in enumerate(images, 1)],
    )


def _png(path, colour):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2), colour).save(path, format="PNG")


def _kit_image(path):
    return "/assets/" + hashlib.sha256(path.read_bytes()).hexdigest()[:12] + ".png"


def _assemble(module, comp, dest):
    main = module.assemble(comp, dest)
    assert main == dest / "main.typ"
    return json.loads((dest / "composition.json").read_text())["sections"]


def test_D1_image_is_copied_and_exposed_in_content(tmp_path):
    module = _interface()
    source = tmp_path / "first" / "picture.png"
    _png(source, (255, 0, 0))
    comp = module.compose(_document("picture.png"), assets=[source.parent])
    sections = _assemble(module, comp, tmp_path / "kit")
    expected = _kit_image(source)
    assert sections[0]["content"]["image"] == expected
    assert (tmp_path / "kit" / expected.lstrip("/")).read_bytes() == source.read_bytes()


def test_D2_searches_folders_in_order(tmp_path):
    module = _interface()
    first, second = tmp_path / "first", tmp_path / "second"
    _png(first / "shared.png", (255, 0, 0))
    _png(second / "shared.png", (0, 0, 255))
    _png(second / "only.png", (0, 255, 0))
    comp = module.compose(_document("only.png", "shared.png"), assets=[first, second])
    sections = _assemble(module, comp, tmp_path / "kit")
    assert [section["content"]["image"] for section in sections] == [
        _kit_image(second / "only.png"), _kit_image(first / "shared.png")
    ]
    for section, source in zip(sections, [second / "only.png", first / "shared.png"], strict=True):
        assert (tmp_path / "kit" / section["content"]["image"].lstrip("/")).read_bytes() == source.read_bytes()


def test_D3_identical_bytes_share_one_copied_file(tmp_path):
    module = _interface()
    assets = tmp_path / "source"
    _png(assets / "one.png", (255, 0, 0))
    (assets / "two.png").write_bytes((assets / "one.png").read_bytes())
    comp = module.compose(_document("one.png", "two.png"), assets=[assets])
    sections = _assemble(module, comp, tmp_path / "kit")
    expected = _kit_image(assets / "one.png")
    assert [section["content"]["image"] for section in sections] == [expected, expected]
    files = list((tmp_path / "kit" / "assets").iterdir())
    assert files == [tmp_path / "kit" / expected.lstrip("/")]
    assert files[0].read_bytes() == (assets / "one.png").read_bytes()


def test_D4_missing_image_reports_file_and_all_searched_folders(tmp_path):
    module = _interface()
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    with pytest.raises(module.ComposeError) as caught:
        module.compose(_document("missing.png"), assets=[first, second])
    message = str(caught.value)
    assert "missing.png" in message
    assert str(first) in message
    assert str(second) in message


def test_D5_no_image_keeps_empty_content_image(tmp_path):
    module = _interface()
    comp = module.compose(_document(None))
    sections = _assemble(module, comp, tmp_path / "kit")
    assert sections[0]["content"]["image"] == ""
