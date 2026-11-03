# Intent: the tree stays clean from the first commit: one editor config, LF line endings, no earlier working names.
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMES = re.compile(r"\b(replo|docklo|proof)\b", re.IGNORECASE)


def _tracked():
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [p for p in out.split("\0") if p and (ROOT / p).is_file()]


def _sections(text):
    sections = {}
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            sections.setdefault(current, {})[key.strip().lower()] = value.strip().lower()
    return sections


def test_D1_editorconfig():
    path = ROOT / ".editorconfig"
    assert path.is_file(), ".editorconfig must exist at the repo root"
    sections = _sections(path.read_text(encoding="utf-8"))
    assert sections.get("", {}).get("root") == "true"
    star = sections.get("*", {})
    assert star.get("charset") == "utf-8"
    assert star.get("end_of_line") == "lf"
    assert star.get("insert_final_newline") == "true"
    py = sections.get("*.py", {})
    assert py.get("indent_style") == "space"
    assert py.get("indent_size") == "4"


def test_D2_gitattributes_eol_lf():
    path = ROOT / ".gitattributes"
    assert path.is_file(), ".gitattributes must exist"
    assert "eol=lf" in path.read_text(encoding="utf-8")


def test_D3_no_carriage_returns():
    offenders = []
    for name in _tracked():
        data = (ROOT / name).read_bytes()
        if b"\0" in data:
            continue
        if b"\r" in data:
            offenders.append(name)
    assert offenders == []


def test_D4_no_earlier_working_names():
    offenders = []
    for name in _tracked():
        if name.startswith("docs/") or name in {"uv.lock", "tests/test_hygiene.py", "tests/judge/test_p0_3_hygiene.py"}:
            continue
        data = (ROOT / name).read_bytes()
        if b"\0" in data:
            continue
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if NAMES.search(line) and "name-gate: allow" not in line:
                offenders.append(f"{name}:{number}")
    assert offenders == []
