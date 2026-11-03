# Intent: every commit needs a Developer Certificate of Origin sign-off, checkable by scripts/check_dco.py.
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_dco.py"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"

SIGN = "Signed-off-by: A B <a@example.com>"

check_dco = None
if SCRIPT.is_file():
    _spec = importlib.util.spec_from_file_location("check_dco", SCRIPT)
    if _spec is not None and _spec.loader is not None:
        check_dco = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(check_dco)


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "T",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "T",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    result = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base commit")
    return repo


def _commit(repo: Path, subject: str, signed: bool) -> str:
    message = subject + "\n\nBody text.\n"
    if signed:
        message += "\n" + SIGN + "\n"
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "--short", "HEAD")


def _run(repo: Path, rev_range: str) -> subprocess.CompletedProcess[str]:
    assert SCRIPT.is_file(), "scripts/check_dco.py must exist"
    return subprocess.run(
        [sys.executable, str(SCRIPT), rev_range], cwd=repo, capture_output=True, text=True
    )


def test_D1_contributing_explains_dco():
    assert CONTRIBUTING.is_file(), "CONTRIBUTING.md must exist"
    text = CONTRIBUTING.read_text(encoding="utf-8")
    assert "Developer Certificate of Origin" in text
    assert "git commit -s" in text
    assert "Signed-off-by:" in text


def test_D2_find_unsigned_returns_position_of_unsigned_message():
    assert check_dco is not None and hasattr(check_dco, "find_unsigned"), "find_unsigned must exist"
    messages = ["Add feature\n\n" + SIGN + "\n", "Fix bug\n\nNo sign-off here\n"]
    assert check_dco.find_unsigned(messages) == [1]


def test_D2_find_unsigned_reports_every_unsigned_and_none_when_all_signed():
    assert check_dco is not None and hasattr(check_dco, "find_unsigned"), "find_unsigned must exist"
    messages = ["one", "two\n\n" + SIGN, "three\n\nSigned-off-by: nobody", SIGN + "\n"]
    assert check_dco.find_unsigned(messages) == [0, 2]
    assert check_dco.find_unsigned(["x\n\n" + SIGN]) == []


def test_D3_all_signed_range_exits_zero(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "first change", signed=True)
    _commit(repo, "second change", signed=True)
    result = _run(repo, "main~2..HEAD")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "unsigned:" not in result.stdout


def test_D3_unsigned_merge_commit_is_skipped(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "topic")
    _commit(repo, "topic change", signed=True)
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main change", signed=True)
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge topic without sign-off", "topic")
    result = _run(repo, "main~2..main")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "unsigned:" not in result.stdout


def test_D4_unsigned_commit_exits_one_and_names_it(tmp_path):
    repo = _repo(tmp_path)
    signed_hash = _commit(repo, "good change", signed=True)
    bad_hash = _commit(repo, "bad change", signed=False)
    result = _run(repo, "main~2..HEAD")
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"unsigned: {bad_hash} bad change" in result.stdout
    assert signed_hash not in result.stdout


def test_D5_empty_range_exits_zero(tmp_path):
    repo = _repo(tmp_path)
    result = _run(repo, "HEAD..HEAD")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "unsigned:" not in result.stdout
