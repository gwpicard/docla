# Intent: ruff skips the frozen judge tests under tests/judge/ but still lints and formats all other code.
import shutil
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SAMPLE = "x   =  1\n# " + "a" * 148 + "\n"


def _ruff(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(ROOT), "ruff", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=540,
    )


def _sandbox(tmp_path: Path, folder: str) -> Path:
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    target = tmp_path / folder
    target.mkdir(parents=True)
    (target / "sample.py").write_text(SAMPLE, encoding="utf-8")
    return tmp_path


def test_D1_extend_exclude_lists_docs_and_tests_judge():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    exclude = config["tool"]["ruff"]["extend-exclude"]
    assert "docs" in exclude
    assert "tests/judge" in exclude


def test_D2_judge_folder_file_passes_ruff_check_and_format(tmp_path):
    cwd = _sandbox(tmp_path, "tests/judge")
    check = _ruff(cwd, "check", ".")
    assert check.returncode == 0, check.stdout + check.stderr
    fmt = _ruff(cwd, "format", "--check", ".")
    assert fmt.returncode == 0, fmt.stdout + fmt.stderr


def test_D3_other_test_folder_still_fails_ruff_format(tmp_path):
    cwd = _sandbox(tmp_path, "tests/other")
    fmt = _ruff(cwd, "format", "--check", ".")
    assert fmt.returncode == 1, fmt.stdout + fmt.stderr
    assert "sample.py" in fmt.stdout + fmt.stderr


def test_D4_repository_passes_ruff_check_and_format():
    check = _ruff(ROOT, "check", ".")
    assert check.returncode == 0, check.stdout + check.stderr
    fmt = _ruff(ROOT, "format", "--check", ".")
    assert fmt.returncode == 0, fmt.stdout + fmt.stderr
