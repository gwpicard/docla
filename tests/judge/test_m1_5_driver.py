# Intent: the Typst driver compiles .typ to deterministic PDF with pinned flags and refuses any Typst but 0.15.1.
import pytest

try:
    from docla.render import typst
except ImportError as error:
    if error.name not in ("docla.render", "docla.render.typst") and not str(error.name).startswith("docla.render."):
        raise
    typst = None

try:
    from docla import cli
except ImportError as error:
    if error.name != "docla" and not str(error.name).startswith("docla."):
        raise
    cli = None


def _require_driver():
    assert typst is not None and hasattr(typst, "compile_pdf"), "docla.render.typst.compile_pdf must exist"


def _fake_typst(folder, version_line):
    """A fake typst that logs compile calls and writes a small output file."""
    log = folder / "calls.log"
    script = folder / "typst"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo \'VERSION_LINE\'; exit 0; fi\n'
        '{ echo "SDE=$SOURCE_DATE_EPOCH"; for a in "$@"; do echo "$a"; done; } >> "LOG"\n'
        "printf '%%PDF-fake' > \"$3\"\n".replace("VERSION_LINE", version_line).replace("LOG", str(log))
    )
    script.chmod(0o755)
    return log


def _paths(tmp_path):
    root = tmp_path / "root"
    root.mkdir(exist_ok=True)
    main = root / "main.typ"
    main.write_text("#set page(width: 100pt, height: 100pt)\nHello\n")
    return main, root, tmp_path / "out.pdf"


def test_D1_same_source_compiles_to_identical_bytes(tmp_path):
    _require_driver()
    main, root, _ = _paths(tmp_path)
    first, second = tmp_path / "a.pdf", tmp_path / "b.pdf"
    typst.compile_pdf(main, root, first)
    typst.compile_pdf(main, root, second)
    assert first.read_bytes().startswith(b"%PDF")
    assert first.read_bytes() == second.read_bytes()


def test_D2_compile_runs_pinned_flags_and_source_date_epoch(tmp_path, monkeypatch):
    _require_driver()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _fake_typst(bin_dir, "typst 0.15.1 (abc123)")
    monkeypatch.setenv("PATH", str(bin_dir))
    main, root, output = _paths(tmp_path)
    font_a, font_b = tmp_path / "fa", tmp_path / "fb"
    typst.compile_pdf(main, root, output, font_paths=[font_a, font_b])
    assert log.read_text().splitlines() == [
        "SDE=0",
        "compile",
        str(main),
        str(output),
        "--root",
        str(root),
        "--ignore-system-fonts",
        "--font-path",
        str(font_a),
        "--font-path",
        str(font_b),
    ]
    assert output.read_bytes() == b"%PDF-fake"


def test_D3_other_version_is_refused_without_compiling(tmp_path, monkeypatch):
    _require_driver()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = _fake_typst(bin_dir, "typst 0.14.0")
    monkeypatch.setenv("PATH", str(bin_dir))
    main, root, output = _paths(tmp_path)
    with pytest.raises(typst.TypstVersionError) as caught:
        typst.compile_pdf(main, root, output)
    assert "0.14.0" in str(caught.value)
    assert "0.15.1" in str(caught.value)
    assert not log.exists()
    assert not output.exists()


def test_D4_missing_typst_raises_not_found(tmp_path, monkeypatch):
    _require_driver()
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    main, root, output = _paths(tmp_path)
    with pytest.raises(typst.TypstNotFound) as caught:
        typst.compile_pdf(main, root, output)
    assert "brew install typst" in str(caught.value)


def test_D5_compile_error_carries_stderr_and_leaves_no_output(tmp_path):
    _require_driver()
    root = tmp_path / "root"
    root.mkdir()
    main = root / "main.typ"
    main.write_text('#panic("docla-boom")\n')
    output = tmp_path / "out.pdf"
    with pytest.raises(typst.TypstCompileError) as caught:
        typst.compile_pdf(main, root, output)
    assert "docla-boom" in str(caught.value)
    assert not output.exists()


def _doctor_lines(capsys):
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    code = cli.main(["doctor"])
    return code, capsys.readouterr().out.splitlines()


def test_D6_doctor_names_the_needed_version_when_wrong(tmp_path, monkeypatch, capsys):
    _fake_typst(tmp_path, "typst 0.14.0")
    monkeypatch.setenv("PATH", str(tmp_path))
    code, lines = _doctor_lines(capsys)
    assert lines[1:3] == ["typst: 0.14.0", "needs: typst 0.15.1"]
    assert code == 0


def test_D6_doctor_prints_no_needs_line_for_pinned_version(tmp_path, monkeypatch, capsys):
    _fake_typst(tmp_path, "typst 0.15.1 (abc123)")
    monkeypatch.setenv("PATH", str(tmp_path))
    code, lines = _doctor_lines(capsys)
    assert "typst: 0.15.1" in lines
    assert not [line for line in lines if line.startswith("needs:")]
    assert code == 0
