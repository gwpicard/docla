# Intent: `docla doctor` reports the Python and Typst versions found, and the CLI handles --version and unknown subcommands.
import os
import subprocess
import sys

try:
    from docla import cli
except ImportError as error:
    if error.name != "docla" and not str(error.name).startswith("docla."):
        raise
    cli = None


def _require_main():
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"


def _fake_typst(folder, first_line):
    script = folder / "typst"
    script.write_text(f"#!/bin/sh\necho '{first_line}'\necho 'second line'\n")
    script.chmod(0o755)


def _run(argv, capsys):
    """Run main(argv); return (exit code, stdout, stderr)."""
    try:
        code = cli.main(argv)
    except SystemExit as exit_:
        code = exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_doctor_first_line_reports_python_version(tmp_path, monkeypatch, capsys):
    _require_main()
    monkeypatch.setenv("PATH", str(tmp_path))
    code, out, _ = _run(["doctor"], capsys)
    v = sys.version_info
    assert out.splitlines()[0] == f"python: {v.major}.{v.minor}.{v.micro}"
    assert code == 0


def test_D2_doctor_reports_missing_typst(tmp_path, monkeypatch, capsys):
    _require_main()
    monkeypatch.setenv("PATH", str(tmp_path))
    code, out, _ = _run(["doctor"], capsys)
    lines = out.splitlines()
    assert "typst: missing" in lines
    assert lines[lines.index("typst: missing") + 1] == "install: brew install typst"
    assert code == 0


def test_D3_doctor_reports_typst_version(tmp_path, monkeypatch, capsys):
    _require_main()
    _fake_typst(tmp_path, "typst 0.14.0")
    monkeypatch.setenv("PATH", str(tmp_path))
    code, out, _ = _run(["doctor"], capsys)
    lines = out.splitlines()
    assert lines[1] == "typst: 0.14.0"
    assert "typst: missing" not in lines
    assert code == 0


def test_D4_installed_docla_command_runs_doctor(tmp_path):
    scripts = os.path.dirname(sys.executable)
    command = os.path.join(scripts, "docla")
    assert os.path.exists(command), "the installed `docla` command must exist (project.scripts)"
    env = {**os.environ, "PATH": str(tmp_path)}
    result = subprocess.run([command, "doctor"], capture_output=True, text=True, env=env, timeout=60)
    v = sys.version_info
    assert result.stdout.splitlines()[0] == f"python: {v.major}.{v.minor}.{v.micro}"
    assert "typst: missing" in result.stdout.splitlines()
    assert result.returncode == 0


def test_D5_version_prints_docla_0_0_1(capsys):
    _require_main()
    code, out, _ = _run(["--version"], capsys)
    assert out.strip() == "docla 0.0.1"
    assert code == 0


def test_D5_unknown_subcommand_fails_and_names_doctor(capsys):
    _require_main()
    code, out, err = _run(["frobnicate"], capsys)
    assert code != 0
    assert "doctor" in out + err
