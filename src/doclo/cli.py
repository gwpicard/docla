import argparse
import shutil
import subprocess
import sys

from doclo import __version__

MIN_PYTHON = (3, 12)


def _python_line() -> tuple[str, bool]:
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < MIN_PYTHON:
        return f"python: {version} (needs 3.12 or later)", False
    return f"python: {version}", True


def _typst_version(executable: str) -> str:
    result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30)
    words = (result.stdout.splitlines() or [""])[0].split()
    return words[1] if len(words) > 1 else "unknown"


def _typst_lines() -> list[str]:
    executable = shutil.which("typst")
    if executable is None:
        return ["typst: missing", "install: brew install typst"]
    return [f"typst: {_typst_version(executable)}"]


def _doctor() -> int:
    python_line, python_ok = _python_line()
    print(python_line)
    for line in _typst_lines():
        print(line)
    return 0 if python_ok else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doclo")
    parser.add_argument("--version", action="version", version=f"doclo {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="report what is installed and what is missing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    return 1


if __name__ == "__main__":
    sys.exit(main())
