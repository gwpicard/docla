# Intent: the Typst kit in docla.render.kit emits the marks and page setup the Contract describes.
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
PRELUDE = '#import "/lib/marks.typ": *\n#import "/lib/theme.typ": *\n'
SLIDE = "#set page(width: 960pt, height: 540pt, margin: 0pt)\n"


def _kit():
    assert kit is not None and hasattr(kit, "lib_dir"), "docla.render.kit.lib_dir must exist"
    return kit


def _root(tmp_path: Path) -> Path:
    shutil.copytree(_kit().lib_dir(), tmp_path / "lib")
    return tmp_path


def _run(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    assert TYPST is not None, "the typst CLI must be installed"
    env = {**os.environ, "SOURCE_DATE_EPOCH": "0"}
    return subprocess.run(
        [TYPST, *args, "--root", str(root), "--ignore-system-fonts"],
        capture_output=True,
        text=True,
        env=env,
        cwd=root,
    )


def _write(root: Path, source: str) -> Path:
    main = root / "main.typ"
    main.write_text(source)
    return main


def _marks(tmp_path: Path, source: str, label: str = "docla-mark") -> list[dict]:
    root = _root(tmp_path)
    main = _write(root, source)
    done = _run(["eval", f"query(<{label}>).map(it => it.value)", "--in", str(main)], root)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _compile(tmp_path: Path, source: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    root = _root(tmp_path)
    main = _write(root, source)
    out = root / "out.pdf"
    return _run(["compile", str(main), str(out)], root), out


def _near(actual: float, expected: float) -> bool:
    return abs(actual - expected) <= 0.01


def _media_box(pdf: Path) -> list[float]:
    found = re.search(rb"MediaBox\s*\[([^\]]*)\]", pdf.read_bytes())
    assert found is not None, "the PDF must carry a MediaBox"
    return [float(part) for part in found.group(1).split()]


def test_D1_lib_dir_holds_the_kit():
    folder = _kit().lib_dir()
    assert folder.is_dir()
    assert (folder / "marks.typ").is_file()
    assert (folder / "theme.typ").is_file()


def test_D2_sections_emit_ordered_start_and_end_marks(tmp_path: Path):
    source = (
        PRELUDE
        + SLIDE
        + '#section("s1")[#rect(width: 100pt, height: 20pt)]\n'
        + '#section("s2")[#rect(width: 100pt, height: 20pt)]\n'
    )
    marks = _marks(tmp_path, source)
    assert [(m["id"], m["edge"]) for m in marks] == [
        ("s1", "start"),
        ("s1", "end"),
        ("s2", "start"),
        ("s2", "end"),
    ]
    for mark in marks:
        assert mark["kind"] == "section"
        assert {"page", "x", "y"} <= set(mark)
    s1_end, s2_start = marks[1], marks[2]
    assert (s1_end["page"], s1_end["x"], s1_end["y"]) == (s2_start["page"], s2_start["x"], s2_start["y"])


def test_D3_el_reports_block_geometry(tmp_path: Path):
    source = PRELUDE + SLIDE + '#place(dx: 100pt, dy: 50pt, el("title", "s1", rect(width: 200pt, height: 40pt)))\n'
    (mark,) = _marks(tmp_path, source)
    assert (mark["kind"], mark["role"], mark["id"], mark["page"]) == ("element", "title", "s1", 1)
    assert _near(mark["x"], 100)
    assert _near(mark["y"], 50)
    assert _near(mark["w"], 200)
    assert _near(mark["h"], 40)


def test_D3_el_text_reports_top_edge_not_baseline(tmp_path: Path):
    source = PRELUDE + SLIDE + '#place(dx: 100pt, dy: 50pt, el("title", "s1", [Hello]))\n'
    (mark,) = _marks(tmp_path, source)
    assert _near(mark["x"], 100)
    assert _near(mark["y"], 50)


def _fit_source(body_height: int) -> str:
    return (
        PRELUDE
        + SLIDE
        + '#el("wrap", "s1", fit-box("body", "s1", 200pt, 40pt, '
        + f"rect(width: 200pt, height: {body_height}pt)))\n"
    )


def test_D4_fit_box_that_fits(tmp_path: Path):
    marks = _marks(tmp_path, _fit_source(30))
    (fit,) = [m for m in marks if m["kind"] == "fit"]
    (wrap,) = [m for m in marks if m["kind"] == "element"]
    assert (fit["role"], fit["id"]) == ("body", "s1")
    assert fit["have"] == 40
    assert fit["ok"] is True
    assert _near(fit["need"], 30)
    assert _near(wrap["h"], 40)


def test_D4_fit_box_that_overflows(tmp_path: Path):
    marks = _marks(tmp_path, _fit_source(60))
    (fit,) = [m for m in marks if m["kind"] == "fit"]
    (wrap,) = [m for m in marks if m["kind"] == "element"]
    assert fit["have"] == 40
    assert fit["ok"] is False
    assert _near(fit["need"], 60)
    assert _near(wrap["h"], 40)


def test_D4_fit_box_uses_no_separate_fit_label(tmp_path: Path):
    assert _marks(tmp_path, _fit_source(60), label="docla-fit") == []


def test_D5_slides_page_setup(tmp_path: Path):
    done, out = _compile(tmp_path, PRELUDE + '#show: page-setup.with("slides")\nHello\n')
    assert done.returncode == 0, done.stderr
    assert _media_box(out) == [0, 0, 960, 540]


def test_D5_doc_page_setup_is_a4(tmp_path: Path):
    done, out = _compile(tmp_path, PRELUDE + '#show: page-setup.with("doc")\nHello\n')
    assert done.returncode == 0, done.stderr
    box = _media_box(out)
    assert box[0] == 0 and box[1] == 0
    assert _near(box[2], 595.28)
    assert _near(box[3], 841.89)


def test_D5_unknown_format_names_the_valid_ones(tmp_path: Path):
    done, _ = _compile(tmp_path, PRELUDE + '#show: page-setup.with("poster")\nHello\n')
    assert done.returncode != 0
    assert "slides" in done.stderr
    assert "doc" in done.stderr


def test_D6_known_colour_compiles_as_fill(tmp_path: Path):
    done, _ = _compile(tmp_path, PRELUDE + '#rect(width: 10pt, height: 10pt, fill: colour("accent"))\n')
    assert done.returncode == 0, done.stderr


def test_D6_unknown_colour_names_the_token(tmp_path: Path):
    done, _ = _compile(tmp_path, PRELUDE + '#rect(fill: colour("nope"))\n')
    assert done.returncode != 0
    assert "nope" in done.stderr


def test_D6_theme_leaves_flow_defaults_alone():
    for name in ("marks.typ", "theme.typ"):
        text = (_kit().lib_dir() / name).read_text()
        assert "costs" not in text
        assert "sticky" not in text
