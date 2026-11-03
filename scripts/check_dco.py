"""Check that every commit in a git revision range carries a DCO sign-off."""

import re
import subprocess
import sys

SIGN_OFF = re.compile(r"^Signed-off-by: .+ <[^<>\s]+@[^<>\s]+>\s*$", re.MULTILINE)


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


def main(argv: list[str]) -> int:
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
