"""Check DCO sign-offs, either on every commit in a git revision range or in a pull request description."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SIGN_OFF = re.compile(r"^Signed-off-by: .+ <[^<>\s]+@[^<>\s]+>\s*$", re.MULTILINE)
MISSING_PR_SIGN_OFF = "missing sign-off: add a Signed-off-by line to the pull request description"


def find_unsigned(messages: list[str]) -> list[int]:
    return [i for i, message in enumerate(messages) if not SIGN_OFF.search(message)]


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    return result.stdout


def read_commits(rev_range: str) -> list[tuple[str, str, str]]:
    """Return (short hash, subject, message) for each non-merge commit in the range."""
    hashes = _git("log", "--no-merges", "--format=%H", rev_range).split()
    commits = []
    for full in hashes:
        message = _git("log", "-1", "--format=%B", full)
        short = _git("rev-parse", "--short", full).strip()
        subject = message.strip().splitlines()[0] if message.strip() else ""
        commits.append((short, subject, message))
    return commits


def pr_signed_off(body: str | None, author: str, owner: str, maintainers: set[str]) -> tuple[bool, str]:
    exempt = {owner.lower(), *(login.lower() for login in maintainers)}
    if author.lower() in exempt:
        return True, f"maintainer: {author}"
    if body and SIGN_OFF.search(body):
        return True, "signed off"
    return False, MISSING_PR_SIGN_OFF


def read_maintainers(path: Path) -> set[str]:
    """Return the GitHub logins listed one per line, skipping blank lines and # comments."""
    if not path.is_file():
        return set()
    lines = (line.strip() for line in path.read_text().splitlines())
    return {line for line in lines if line and not line.startswith("#")}


def check_pr_event(event_path: Path, maintainers_path: Path) -> int:
    event = json.loads(event_path.read_text())
    pull_request = event["pull_request"]
    ok, message = pr_signed_off(
        pull_request.get("body"),
        pull_request["user"]["login"],
        event["repository"]["owner"]["login"],
        read_maintainers(maintainers_path),
    )
    print(message)
    return 0 if ok else 1


def _pr_mode(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="check_dco.py")
    parser.add_argument("--pr-event", type=Path, required=True)
    parser.add_argument("--maintainers", type=Path, default=Path("MAINTAINERS"))
    args = parser.parse_args(argv[1:])
    return check_pr_event(args.pr_event, args.maintainers)


def main(argv: list[str]) -> int:
    if "--pr-event" in argv:
        return _pr_mode(argv)
    if len(argv) != 2:
        print("usage: check_dco.py <revision-range>", file=sys.stderr)
        return 2
    commits = read_commits(argv[1])
    unsigned = find_unsigned([message for _, _, message in commits])
    for index in unsigned:
        short, subject, _ = commits[index]
        print(f"unsigned: {short} {subject}")
    return 1 if unsigned else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
