"""Scan git-tracked files for well-known secret shapes. Never prints the matched text."""

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}")),
    ("aws-key-id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github-token", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
ALLOW_MARKER = "secret-scan: allow"


def find_secrets(text: str) -> list[tuple[int, str]]:
    """Return (line number, kind) for each line that matches a secret pattern."""
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        for kind, pattern in PATTERNS:
            if pattern.search(line):
                findings.append((number, kind))
                break
    return findings


def tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, check=True)
    return [path for path in result.stdout.split("\0") if path]


def read_text(path: str) -> str | None:
    try:
        return Path(path).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def main() -> int:
    found = False
    for path in tracked_files():
        text = read_text(path)
        if text is None:
            continue
        for number, kind in find_secrets(text):
            print(f"{path}:{number}: {kind}")
            found = True
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
