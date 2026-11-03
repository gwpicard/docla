# Intent: the DCO is checked once per pull request description, with maintainers exempt, by scripts/check_dco.py.
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_dco.py"
MAINTAINERS = ROOT / "MAINTAINERS"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"

SIGN = "Signed-off-by: A B <a@example.com>"
MISSING = "missing sign-off: add a Signed-off-by line to the pull request description"

check_dco = None
if SCRIPT.is_file():
    _spec = importlib.util.spec_from_file_location("check_dco_pr", SCRIPT)
    if _spec is not None and _spec.loader is not None:
        check_dco = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(check_dco)


def _event(tmp_path: Path, author: str, body: str | None, owner: str = "gwpicard") -> Path:
    path = tmp_path / "event.json"
    path.write_text(
        json.dumps(
            {
                "pull_request": {"user": {"login": author}, "body": body},
                "repository": {"owner": {"login": owner}},
            }
        )
    )
    return path


def _maintainers(tmp_path: Path, text: str = "# maintainers\ngwpicard\nalice\n") -> Path:
    path = tmp_path / "MAINTAINERS"
    path.write_text(text)
    return path


def _run_pr(tmp_path: Path, event: Path, maintainers: Path) -> subprocess.CompletedProcess[str]:
    assert SCRIPT.is_file(), "scripts/check_dco.py must exist"
    work = tmp_path / "not-a-repo"
    work.mkdir(exist_ok=True)
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--pr-event", str(event), "--maintainers", str(maintainers)],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
    )


def test_D1_owner_is_exempt(tmp_path):
    result = _run_pr(tmp_path, _event(tmp_path, "gwpicard", "no sign-off"), _maintainers(tmp_path, ""))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "maintainer: gwpicard"


def test_D1_listed_maintainer_is_exempt_whatever_the_body(tmp_path):
    result = _run_pr(tmp_path, _event(tmp_path, "alice", None), _maintainers(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "maintainer: alice"


def test_D1_maintainer_comparison_ignores_case(tmp_path):
    result = _run_pr(tmp_path, _event(tmp_path, "Alice", ""), _maintainers(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "maintainer: Alice"


def test_D1_pr_signed_off_maintainer():
    assert check_dco is not None and hasattr(check_dco, "pr_signed_off"), "pr_signed_off must exist"
    assert check_dco.pr_signed_off("", "Bob", "owner", {"bob"}) == (True, "maintainer: Bob")
    assert check_dco.pr_signed_off(None, "OWNER", "owner", set()) == (True, "maintainer: OWNER")


def test_D2_signed_non_maintainer_passes_outside_a_git_repo(tmp_path):
    body = f"Adds a thing.\n\n{SIGN}\n"
    result = _run_pr(tmp_path, _event(tmp_path, "carol", body), _maintainers(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "signed off"


def test_D2_pr_signed_off_accepts_sign_off_line():
    assert check_dco is not None and hasattr(check_dco, "pr_signed_off"), "pr_signed_off must exist"
    assert check_dco.pr_signed_off(f"text\n{SIGN}\nmore", "carol", "o", set()) == (True, "signed off")


def test_D3_body_without_sign_off_fails(tmp_path):
    body = "Adds a thing. Signed-off-by is mentioned but not as a trailer."
    result = _run_pr(tmp_path, _event(tmp_path, "carol", body), _maintainers(tmp_path))
    assert result.returncode == 1
    assert result.stdout.strip() == MISSING


def test_D3_empty_body_fails(tmp_path):
    result = _run_pr(tmp_path, _event(tmp_path, "carol", ""), _maintainers(tmp_path))
    assert result.returncode == 1
    assert result.stdout.strip() == MISSING


def test_D3_null_body_fails(tmp_path):
    result = _run_pr(tmp_path, _event(tmp_path, "carol", None), _maintainers(tmp_path))
    assert result.returncode == 1
    assert result.stdout.strip() == MISSING


def test_D3_pr_signed_off_missing():
    assert check_dco is not None and hasattr(check_dco, "pr_signed_off"), "pr_signed_off must exist"
    assert check_dco.pr_signed_off(None, "carol", "o", set()) == (False, MISSING)
    assert check_dco.pr_signed_off("Signed-off-by: A B", "carol", "o", set()) == (False, MISSING)


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


def test_D4_commit_range_mode_still_works(tmp_path):
    assert SCRIPT.is_file(), "scripts/check_dco.py must exist"
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "signed one\n\n" + SIGN + "\n")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "unsigned one")
    short = _git(repo, "rev-parse", "--short", "HEAD")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "HEAD~2..HEAD"], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 1
    assert result.stdout.strip() == f"unsigned: {short} unsigned one"


def test_D4_find_unsigned_unchanged():
    assert check_dco is not None and hasattr(check_dco, "find_unsigned"), "find_unsigned must exist"
    assert check_dco.find_unsigned(["a\n\n" + SIGN + "\n", "b", "c\n"]) == [1, 2]


def test_D5_maintainers_file_lists_gwpicard():
    assert MAINTAINERS.is_file(), "MAINTAINERS must exist at the repository root"
    lines = MAINTAINERS.read_text().splitlines()
    assert lines[0].startswith("#")
    assert "gwpicard" in [line.strip() for line in lines]
    assert check_dco is not None and hasattr(check_dco, "read_maintainers"), "read_maintainers must exist"
    assert "gwpicard" in check_dco.read_maintainers(MAINTAINERS)


def test_D5_read_maintainers_ignores_blanks_and_comments(tmp_path):
    assert check_dco is not None and hasattr(check_dco, "read_maintainers"), "read_maintainers must exist"
    path = tmp_path / "M"
    path.write_text("# who\n\nalice\n  \n#bob\ncarol\n")
    assert check_dco.read_maintainers(path) == {"alice", "carol"}


def test_D5_read_maintainers_missing_file_is_empty(tmp_path):
    assert check_dco is not None and hasattr(check_dco, "read_maintainers"), "read_maintainers must exist"
    assert check_dco.read_maintainers(tmp_path / "absent") == set()


def test_D6_contributing_states_pull_request_rule():
    assert CONTRIBUTING.is_file(), "CONTRIBUTING.md must exist"
    text = CONTRIBUTING.read_text()
    lowered = text.lower()
    assert "Developer Certificate of Origin" in text
    assert "directly to `main`" in lowered
    assert "Signed-off-by: Your Name <you@example.com>" in text
    assert "pull request description" in lowered
    assert "MAINTAINERS" in text
    assert "exempt" in lowered


def test_D6_contributing_drops_per_commit_instruction():
    assert CONTRIBUTING.is_file(), "CONTRIBUTING.md must exist"
    text = CONTRIBUTING.read_text()
    assert "git commit -s" not in text
    assert "commit --amend -s" not in text
