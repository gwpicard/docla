# Intent: the statement and bullets slide components report their sections, fixed frames and list items through the kit.
import json
import re
import shutil
from pathlib import Path


def _optional(module_name: str):
    import importlib

    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if name != "docla.render" and not name.startswith("docla.render."):
            raise
        return None


kit = _optional("docla.render.kit")
marks = _optional("docla.render.marks")
typst = _optional("docla.render.typst")


def _require_interface() -> None:
    assert kit is not None and hasattr(kit, "components_dir"), "docla.render.kit.components_dir must exist"
    assert hasattr(kit, "lib_dir"), "docla.render.kit.lib_dir must exist"
    assert marks is not None and hasattr(marks, "read_marks"), "docla.render.marks.read_marks must exist"
    assert typst is not None and hasattr(typst, "compile_pdf"), "docla.render.typst.compile_pdf must exist"


def _build(tmp_path: Path, component: str, sec: dict) -> tuple[Path, Path]:
    _require_interface()
    shutil.copytree(kit.lib_dir(), tmp_path / "lib")
    shutil.copytree(kit.components_dir(), tmp_path / "components")
    (tmp_path / "sec.json").write_text(json.dumps(sec))
    main = tmp_path / "main.typ"
    main.write_text(
        '#import "/lib/theme.typ": page-setup\n'
        f'#import "/components/{component}.typ": {component}\n'
        f'#page-setup("slides")[#{component}(json("/sec.json"))]\n'
    )
    return main, tmp_path


def _page_count(pdf: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf.read_bytes()))


def _item(i: int, text: str = "Short body") -> dict:
    return {"head": f"Head {i}", "body": text, "cites": []}


def _bullets_sec(sec_id: str, items: list[dict]) -> dict:
    return {"id": sec_id, "title": "Plan", "items": items, "paragraphs": [], "source_line": ""}


def test_D1_components_dir_holds_both_files():
    _require_interface()
    folder = kit.components_dir()
    assert folder.is_dir()
    assert (folder / "statement.typ").is_file()
    assert (folder / "bullets.typ").is_file()


def test_D2_statement_marks_and_one_page(tmp_path):
    sec = {"id": "s1", "title": "We ship", "items": [], "paragraphs": [], "source_line": ""}
    main, root = _build(tmp_path, "statement", sec)
    result = marks.read_marks(main, root)
    assert [type(m) for m in result] == [marks.SectionMark, marks.FitMark, marks.SectionMark]
    start, fit, end = result
    assert (start.id, start.edge) == ("s1", "start")
    assert (fit.id, fit.role, fit.have) == ("s1", "title", 300)
    assert (end.id, end.edge) == ("s1", "end")
    pdf = tmp_path / "out.pdf"
    typst.compile_pdf(main, root, pdf)
    assert _page_count(pdf) == 1


def test_D3_bullets_marks_for_three_short_items(tmp_path):
    main, root = _build(tmp_path, "bullets", _bullets_sec("s2", [_item(1), _item(2), _item(3)]))
    result = marks.read_marks(main, root)
    fits = [m for m in result if isinstance(m, marks.FitMark)]
    assert [(m.role, m.id) for m in fits] == [("title", "s2"), ("body", "s2")]
    assert fits[1].ok is True
    items = [m for m in result if isinstance(m, marks.ElementMark) and m.role == "item"]
    assert len(items) == 3
    assert all(m.id == "s2" for m in items)
    assert [m.y for m in items] == sorted(m.y for m in items)
    assert len({m.y for m in items}) == 3
    for m in items:
        assert abs(m.x - 40) <= 0.5
        assert m.y >= 120
        assert m.y + m.h >= 120
        assert m.y + m.h <= 500


def test_D4_bullets_overflow_reported_on_one_page(tmp_path):
    items = [_item(i, "word " * 40) for i in range(12)]
    assert all(len(i["body"]) == 200 for i in items)
    main, root = _build(tmp_path, "bullets", _bullets_sec("s3", items))
    body = [m for m in marks.read_marks(main, root) if isinstance(m, marks.FitMark) and m.role == "body"]
    assert len(body) == 1
    assert body[0].ok is False
    assert body[0].need > 380
    pdf = tmp_path / "out.pdf"
    typst.compile_pdf(main, root, pdf)
    assert _page_count(pdf) == 1


def test_D5_component_files_hold_no_colour_literals():
    _require_interface()
    folder = kit.components_dir()
    for name in ("statement.typ", "bullets.typ"):
        text = (folder / name).read_text()
        for literal in ("rgb(", "luma(", "cmyk("):
            assert literal not in text, f"{name} contains {literal}"
        assert re.search(r"#[0-9a-fA-F]{6}", text) is None, f"{name} contains a hex colour"
