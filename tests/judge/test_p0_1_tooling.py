# Intent: the project has one pinned-to-Python-3.12 command each for linting, formatting, type checking and testing.
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=540)


def test_D1_python_version_pinned_to_3_12():
    assert _pyproject()["project"]["requires-python"] == ">=3.12"
    version_file = ROOT / ".python-version"
    assert version_file.is_file(), ".python-version must exist"
    assert version_file.read_text(encoding="utf-8").strip() == "3.12"


def test_D2_ruff_check_passes_with_line_length_120():
    assert _pyproject().get("tool", {}).get("ruff", {}).get("line-length") == 120
    result = _run("uv", "run", "ruff", "check", ".")
    assert result.returncode == 0, result.stdout + result.stderr


def test_D3_ruff_format_check_passes():
    result = _run("uv", "run", "ruff", "format", "--check", ".")
    assert result.returncode == 0, result.stdout + result.stderr


def test_D4_mypy_passes_in_strict_mode():
    assert _pyproject().get("tool", {}).get("mypy", {}).get("strict") is True
    result = _run("uv", "run", "mypy")
    assert result.returncode == 0, result.stdout + result.stderr


def test_D5_pre_commit_config_runs_ruff_and_mypy_through_uv_run():
    config = ROOT / ".pre-commit-config.yaml"
    assert config.is_file(), ".pre-commit-config.yaml must exist"
    text = config.read_text(encoding="utf-8")
    entries = re.findall(r"^\s*(?:-\s*)?entry:\s*(.+?)\s*$", text, flags=re.MULTILINE)
    assert entries, "hooks must declare an entry"
    assert all(entry.startswith("uv run ") for entry in entries), entries
    assert any(entry.startswith("uv run ruff check") for entry in entries), entries
    assert any(entry.startswith("uv run ruff format") for entry in entries), entries
    assert any(entry.startswith("uv run mypy") for entry in entries), entries


def test_D6_gitignore_lists_tool_caches():
    gitignore = ROOT / ".gitignore"
    assert gitignore.is_file(), ".gitignore must exist"
    lines = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
    assert ".ruff_cache/" in lines
    assert ".mypy_cache/" in lines
