# Intent: the body and callout components draw a section with the kit and emit the marks the Contract describes.
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

try:
    from docla.render import kit
except ImportError as error:
    name = str(error.name)
    if name not in ("docla", "docla.render", "docla.render.kit") and not name.startswith("docla.render.kit."):
        raise
    kit = None

TYPST = shutil.which("typst")
A4_TEXT_WIDTH = 595.28 - 2 * (20 * 72 / 25.4)


def _kit():
    assert kit is not None and hasattr(kit, "components_dir"), "docla.render.kit.components_dir must exist"
    assert hasattr(kit, "lib_dir"), "docla.render.kit.lib_dir must exist"
    return kit


def _lit(value: str) -> str:
    return json.dumps(value)


def _sec(sec_id: str, title: str, paragraphs: list[str], items: list[str], source_line: str) -> str:
    item_text = ", ".join(f"(head: {_lit(f'Head {i}')}, body: {_lit(text)}, cites: ())" for i, text in enumerate(items))
    item_text = f"({item_text},)" if items else "()"
    para_text = "(" + ", ".join(_lit(p) for p in paragraphs) + ",)" if paragraphs else "()"
    return (
        f"(id: {_lit(sec_id)}, title: {_lit(title)}, items: {item_text}, "
        f"paragraphs: {para_text}, source_line: {_lit(source_line)})"
    )


def _marks(tmp_path: Path, component: str, sec: str) -> list[dict]:
    k = _kit()
    shutil.copytree(k.lib_dir(), tmp_path / "lib")
    shutil.copytree(k.components_dir(), tmp_path / "components")
    main = tmp_path / "main.typ"
    main.write_text(
        '#import "/lib/theme.typ": page-setup\n'
        f'#import "/components/{component}.typ": {component}\n'
        '#show: page-setup.with("doc")\n'
        f"#{component}({sec})\n"
    )
    assert TYPST is not None, "the typst CLI must be installed"
    done = subprocess.run(
        [
            TYPST,
            "eval",
            "query(<docla-mark>).map(it => it.value)",
            "--in",
            str(main),
            "--root",
            str(tmp_path),
            "--ignore-system-fonts",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "SOURCE_DATE_EPOCH": "0"},
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _near(actual: float, expected: float, tolerance: float = 0.5) -> bool:
    return abs(actual - expected) <= tolerance


def _of(marks: list[dict], kind: str, **fields) -> list[dict]:
    return [m for m in marks if m["kind"] == kind and all(m.get(k) == v for k, v in fields.items())]


SHORT = ["First short paragraph.", "Second short paragraph.", "Third short paragraph."]


def test_D1_components_dir_holds_body_and_callout():
    folder = _kit().components_dir()
    assert (folder / "body.typ").is_file()
    assert (folder / "callout.typ").is_file()


def test_D2_body_emits_section_marks_and_heading_at_the_start(tmp_path: Path):
    marks = _marks(tmp_path, "body", _sec("d1", "Findings", SHORT, [], ""))
    sections = _of(marks, "section")
    assert [(m["id"], m["edge"]) for m in sections] == [("d1", "start"), ("d1", "end")]
    (heading,) = _of(marks, "element", role="heading")
    start = sections[0]
    assert heading["id"] == "d1"
    assert heading["page"] == start["page"]
    assert _near(heading["x"], start["x"])
    assert _near(heading["y"], start["y"])


def test_D3_long_body_spans_pages_with_only_start_and_end_marks(tmp_path: Path):
    paragraphs = [("word " * 80).strip() + "." for _ in range(40)]
    assert all(len(p) == 400 for p in paragraphs)
    marks = _marks(tmp_path, "body", _sec("d1", "Long", paragraphs, [], ""))
    sections = _of(marks, "section")
    assert [(m["id"], m["edge"]) for m in sections] == [("d1", "start"), ("d1", "end")]
    assert sections[0]["page"] == 1
    assert sections[1]["page"] > 1


def test_D4_callout_is_one_block_at_the_text_width(tmp_path: Path):
    marks = _marks(tmp_path, "callout", _sec("d2", "Note", [], ["one", "two", "three"], ""))
    assert [(m["id"], m["edge"]) for m in _of(marks, "section")] == [("d2", "start"), ("d2", "end")]
    (callout,) = _of(marks, "element", role="callout")
    assert callout["id"] == "d2"
    assert _near(callout["w"], A4_TEXT_WIDTH)
    assert callout["h"] > 0


def test_D5_body_source_follows_the_last_paragraph(tmp_path: Path):
    marks = _marks(tmp_path, "body", _sec("d1", "Findings", SHORT, [], "Source: annual report"))
    (heading,) = _of(marks, "element", role="heading")
    (source,) = _of(marks, "element", role="source")
    assert source["id"] == "d1"
    assert source["page"] == heading["page"]
    # a 16 pt heading plus three 11 pt lines
    assert source["y"] - heading["y"] > 50


def test_D5_long_body_source_is_on_the_last_page(tmp_path: Path):
    paragraphs = [("word " * 80).strip() + "." for _ in range(40)]
    marks = _marks(tmp_path, "body", _sec("d1", "Long", paragraphs, [], "Source: annual report"))
    (source,) = _of(marks, "element", role="source")
    end = _of(marks, "section", edge="end")[0]
    assert source["page"] > 1
    assert source["page"] == end["page"]
    assert source["y"] <= end["y"]


def test_D5_empty_source_line_emits_no_source_mark(tmp_path: Path):
    marks = _marks(tmp_path, "body", _sec("d1", "Findings", SHORT, [], ""))
    assert _of(marks, "element", role="source") == []


def test_D6_component_files_hold_no_colour_literals():
    folder = _kit().components_dir()
    for name in ("body.typ", "callout.typ"):
        text = (folder / name).read_text()
        for banned in ("rgb(", "luma(", "cmyk("):
            assert banned not in text, f"{name} must not contain {banned}"
        assert re.search(r"#[0-9a-fA-F]{6}", text) is None, f"{name} must not hold a hex colour"
