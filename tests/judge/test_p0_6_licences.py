# Intent: the licence report lists every installed dependency's licence and fails when one is AGPL.
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "licence_report.py"


def _load():
    if not SCRIPT.exists():
        return None
    spec = importlib.util.spec_from_file_location("licence_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


licence_report = _load()


def _fake_dist(folder: Path, name: str, licence_field: str) -> None:
    info = folder / f"{name}-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n{licence_field}\n", encoding="utf-8"
    )


def _run_cli(extra_path: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if extra_path is not None:
        env["PYTHONPATH"] = os.pathsep.join([str(extra_path), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )


def _exists() -> None:
    assert licence_report is not None, "scripts/licence_report.py must exist"


def test_D1_is_agpl():
    _exists()
    assert licence_report.is_agpl("AGPL-3.0-or-later") is True
    assert licence_report.is_agpl("GNU Affero General Public License v3") is True
    assert licence_report.is_agpl("MIT") is False
    assert licence_report.is_agpl("Apache-2.0") is False


def test_D2_report_lines_sorted_by_name():
    _exists()
    lines, offenders = licence_report.report(
        {"zeta": ("2.0", "MIT"), "alpha": ("1.5", "Apache-2.0"), "mid": ("0.1", "BSD-3-Clause")}
    )
    assert lines == ["alpha 1.5 Apache-2.0", "mid 0.1 BSD-3-Clause", "zeta 2.0 MIT"]
    assert offenders == []


def test_D3_report_lists_agpl_offender():
    _exists()
    lines, offenders = licence_report.report(
        {"pymupdf": ("1.24", "AGPL-3.0-or-later"), "requests": ("2.0", "Apache-2.0")}
    )
    assert offenders == ["pymupdf"]
    assert "pymupdf 1.24 AGPL-3.0-or-later" in lines


def test_D3_command_line_exits_1_on_agpl(tmp_path):
    _exists()
    _fake_dist(tmp_path, "fakeagpl", "License-Expression: AGPL-3.0-or-later")
    result = _run_cli(tmp_path)
    assert result.returncode == 1
    assert "agpl: fakeagpl" in result.stdout.splitlines()
    assert "fakeagpl 1.0 AGPL-3.0-or-later" in result.stdout.splitlines()


def test_D4_unknown_licence_listed_not_offender():
    _exists()
    lines, offenders = licence_report.report({"mystery": ("3.1", "unknown")})
    assert lines == ["mystery 3.1 unknown"]
    assert offenders == []


def test_D4_command_line_unknown_does_not_fail(tmp_path):
    _exists()
    _fake_dist(tmp_path, "fakeunknown", "Summary: no licence declared")
    result = _run_cli(tmp_path)
    assert "fakeunknown 1.0 unknown" in result.stdout.splitlines()
    assert "agpl: fakeunknown" not in result.stdout
    assert result.returncode == 0


def test_D5_project_environment_exits_0():
    _exists()
    command = ["uv", "run", "python", "scripts/licence_report.py"] if shutil.which("uv") else [sys.executable, str(SCRIPT)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() != ""
