# Intent: the CI workflow runs lint, types, tests, DCO, licence and secret checks on push and pull request, on macOS and Linux.
import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _text() -> str:
    assert WORKFLOW.is_file(), ".github/workflows/ci.yml must exist"
    return WORKFLOW.read_text(encoding="utf-8")


def _jobs() -> dict[str, list[str]]:
    lines = _text().splitlines()
    start = next((i for i, line in enumerate(lines) if re.fullmatch(r"jobs:\s*", line)), None)
    assert start is not None, "ci.yml must define jobs:"
    jobs: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines[start + 1 :]:
        header = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", line)
        if header:
            current = jobs.setdefault(header.group(1), [])
        elif current is not None:
            current.append(line)
    return jobs


def _commands(job: list[str]) -> set[str]:
    found = set()
    for line in job:
        cmd = line.strip()
        cmd = re.sub(r"^-\s*", "", cmd)
        cmd = re.sub(r"^run:\s*[|>]?\s*", "", cmd)
        found.add(cmd.strip())
    return found


def _block(lines: list[str], key: str, indent: int) -> list[str]:
    """Lines nested under `key:` at the given indent."""
    for i, line in enumerate(lines):
        if re.fullmatch(" " * indent + re.escape(key) + r":.*", line):
            body = [line.split(":", 1)[1]]
            for nxt in lines[i + 1 :]:
                if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                    break
                body.append(nxt)
            return body
    return []


def test_D1_triggers_on_pull_request_and_push_to_main():
    lines = _text().splitlines()
    on_start = next((i for i, line in enumerate(lines) if re.match(r"""["']?on["']?:""", line)), None)
    assert on_start is not None, "ci.yml must have an on: section"
    section = []
    for line in lines[on_start:]:
        if line.startswith("jobs:"):
            break
        section.append(line)
    assert _block(section, "pull_request", 2), "must trigger on pull_request"
    push = _block(section, "push", 2)
    assert push, "must trigger on push"
    assert re.search(r"\bmain\b", "\n".join(push)), "push must be limited to main"


def test_D2_checks_job_runs_on_ubuntu_and_macos_with_all_checks():
    required = {
        "uv sync",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run mypy",
        "uv run python -m pytest",
    }
    matches = [
        name
        for name, job in _jobs().items()
        if "ubuntu-latest" in "\n".join(job)
        and "macos-latest" in "\n".join(job)
        and required <= _commands(job)
    ]
    assert matches, "a job must cover ubuntu-latest, macos-latest and all five commands"
    body = "\n".join(_jobs()[matches[0]])
    assert "matrix" in body and "${{ matrix.os }}" in body, "runs-on must use the os matrix"
    assert "astral-sh/setup-uv@" in body, "job must install uv with astral-sh/setup-uv"


def test_D2_every_job_installs_uv_and_syncs():
    jobs = _jobs()
    assert {"checks", "dco", "licences", "secrets"} <= set(jobs)
    for name, job in jobs.items():
        assert "astral-sh/setup-uv@" in "\n".join(job), f"{name} must install uv"
        assert "uv sync" in _commands(job), f"{name} must run uv sync"


def test_D6_dco_job_checks_the_pull_request_event_without_history():
    jobs = _jobs()
    assert "dco" in jobs, "a dco job must exist"
    body = "\n".join(jobs["dco"])
    condition = [line.strip() for line in jobs["dco"] if line.strip().startswith("if:")]
    assert condition and "github.event_name == 'pull_request'" in condition[0], (
        "dco must run only on pull_request"
    )
    expected = 'scripts/check_dco.py --pr-event "$GITHUB_EVENT_PATH" --maintainers MAINTAINERS'
    checks = [cmd for cmd in _commands(jobs["dco"]) if "scripts/check_dco.py" in cmd]
    assert len(checks) == 1, "dco must invoke scripts/check_dco.py exactly once"
    assert checks[0].endswith(expected), f"dco must run check_dco.py with: {expected}"
    assert "..HEAD" not in body and "base_ref" not in body, "dco must not pass a commit range"
    assert not re.search(r"fetch-depth", body), "dco must not fetch full history"


def test_D4_licences_and_secrets_jobs_run_their_scripts():
    jobs = _jobs()
    assert "licences" in jobs, "a licences job must exist"
    assert "secrets" in jobs, "a secrets job must exist"
    assert "uv run python scripts/licence_report.py" in _commands(jobs["licences"])
    assert "uv run python scripts/scan_secrets.py" in _commands(jobs["secrets"])


def test_D5_every_uses_line_pins_a_version():
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", _text(), flags=re.MULTILINE)
    assert uses, "workflow must use at least one action"
    for ref in uses:
        assert re.fullmatch(r"[^@\s]+@[^@\s]+", ref), f"uses: {ref} must name a version after @"
