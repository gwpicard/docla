# Intent: read_marks returns the semantic marks of a laid-out Typst document as typed models, using `typst eval`.
import json
import shutil
import stat
from pathlib import Path

import pytest


def _optional(module_name: str):
    import importlib

    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if name != "docla.render" and not name.startswith("docla.render."):
            raise
        return None


marks = _optional("docla.render.marks")
typst = _optional("docla.render.typst")
kit = _optional("docla.render.kit")


def _require_interface() -> None:
    assert marks is not None and hasattr(marks, "read_marks"), "docla.render.marks.read_marks must exist"
    for name in ("SectionMark", "ElementMark", "FitMark", "MarkError"):
        assert hasattr(marks, name), f"docla.render.marks.{name} must exist"
    assert typst is not None, "docla.render.typst must exist"


REAL_SOURCE = """\
#import "/lib/marks.typ": section, el, fit-box
#set page(width: 400pt, height: 300pt, margin: 0pt)
#section("s1")[
  #pad(left: 30pt, top: 50pt)[
    #el("title", "s1", [Hello])
  ]
  #fit-box("body", "s1", 200pt, 40pt, [Some body text])
]
"""


def _real_project(tmp_path: Path, source: str) -> tuple[Path, Path]:
    assert kit is not None and hasattr(kit, "lib_dir"), "docla.render.kit.lib_dir must exist"
    shutil.copytree(kit.lib_dir(), tmp_path / "lib")
    main = tmp_path / "main.typ"
    main.write_text(source)
    return main, tmp_path


def _fake_typst(tmp_path: Path, monkeypatch, version: str, output: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "record.txt"
    out = tmp_path / "out.json"
    out.write_text(output)
    script = bin_dir / "typst"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then\n'
        f"  echo '{version}'\n"
        "  exit 0\n"
        "fi\n"
        f'echo "ARGS:$*" >> "{record}"\n'
        f'echo "EPOCH:$SOURCE_DATE_EPOCH" >> "{record}"\n'
        f'cat "{out}"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return record


def _section(i: int) -> dict:
    return {"kind": "section", "id": f"s{i}", "edge": "start", "page": 1, "x": 0, "y": 0}


def test_D1_real_typst_returns_ordered_typed_marks(tmp_path):
    _require_interface()
    main, root = _real_project(tmp_path, REAL_SOURCE)
    result = marks.read_marks(main, root)
    assert [type(m) for m in result] == [
        marks.SectionMark,
        marks.ElementMark,
        marks.FitMark,
        marks.SectionMark,
    ]
    start, element, fit, end = result
    assert (start.id, start.edge) == ("s1", "start")
    assert (end.id, end.edge) == ("s1", "end")
    assert (element.role, element.id) == ("title", "s1")
    assert element.x == pytest.approx(30, abs=0.01)
    assert element.y == pytest.approx(50, abs=0.01)
    assert (fit.role, fit.id) == ("body", "s1")


def test_D2_runs_typst_eval_with_pinned_flags(tmp_path, monkeypatch):
    _require_interface()
    record = _fake_typst(tmp_path, monkeypatch, "typst 0.15.1 (abc)", "[]")
    main = tmp_path / "main.typ"
    main.write_text("")
    font = tmp_path / "fonts"
    marks.read_marks(main, tmp_path, font_paths=[font])
    lines = record.read_text().splitlines()
    assert lines == [
        f"ARGS:eval query(<docla-mark>).map(it => it.value) --in {main} --root {tmp_path}"
        f" --ignore-system-fonts --font-path {font}",
        "EPOCH:0",
    ]


def test_D3_wrong_version_raises_and_never_evals(tmp_path, monkeypatch):
    _require_interface()
    record = _fake_typst(tmp_path, monkeypatch, "typst 0.14.0 (abc)", "[]")
    main = tmp_path / "main.typ"
    main.write_text("")
    with pytest.raises(typst.TypstVersionError):
        marks.read_marks(main, tmp_path)
    assert not record.exists()


def test_D4_compile_error_carries_typst_stderr(tmp_path):
    _require_interface()
    main, root = _real_project(tmp_path, '#panic("docla-boom")\n')
    with pytest.raises(typst.TypstCompileError) as info:
        marks.read_marks(main, root)
    assert "docla-boom" in str(info.value)


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "banana", "id": "s2"},
        {"kind": "section", "id": "s2", "page": 1, "x": 0, "y": 0},
    ],
    ids=["unknown-kind", "missing-edge"],
)
def test_D5_invalid_mark_raises_mark_error_naming_index(tmp_path, monkeypatch, bad):
    _require_interface()
    _fake_typst(tmp_path, monkeypatch, "typst 0.15.1 (abc)", json.dumps([_section(0), _section(1), bad, _section(3)]))
    main = tmp_path / "main.typ"
    main.write_text("")
    with pytest.raises(marks.MarkError) as info:
        marks.read_marks(main, tmp_path)
    assert isinstance(info.value, ValueError)
    assert "2" in str(info.value)


def test_D6_document_without_marks_returns_empty_list(tmp_path):
    _require_interface()
    main, root = _real_project(tmp_path, "#set page(width: 100pt, height: 100pt)\nHello\n")
    assert marks.read_marks(main, root) == []
