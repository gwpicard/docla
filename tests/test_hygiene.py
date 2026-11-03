import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = re.compile(r"\b(replo|docklo|doclo|proof)\b", re.IGNORECASE)
NAME_EXEMPT = {"uv.lock", "tests/test_hygiene.py", "tests/judge/test_p0_3_hygiene.py"}


def _tracked_text():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode()
    for name in out.split("\0"):
        if not name or not (ROOT / name).is_file():
            continue
        data = (ROOT / name).read_bytes()
        if b"\0" not in data:
            yield name, data


def _name_hits(name, data):
    text = data.decode("utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), 1):
        if NAMES.search(line) and "name-gate: allow" not in line:
            yield f"{name}:{number}"


def test_no_carriage_returns():
    offenders = [name for name, data in _tracked_text() if b"\r" in data]
    assert offenders == []


def test_no_earlier_working_names():
    offenders = []
    for name, data in _tracked_text():
        if name.startswith("docs/") or name in NAME_EXEMPT:
            continue
        offenders.extend(_name_hits(name, data))
    assert offenders == []
