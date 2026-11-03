import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

TYPST_VERSION = "0.15.1"
INSTALL_COMMAND = "brew install typst"


class TypstError(Exception):
    pass


class TypstNotFound(TypstError):
    pass


class TypstVersionError(TypstError):
    pass


class TypstCompileError(TypstError):
    pass


def parse_version(version_output: str) -> str:
    """`typst --version` prints a line such as `typst 0.15.1 (abc123)`, so the version is its second word."""
    words = (version_output.splitlines() or [""])[0].split()
    return words[1] if len(words) > 1 else "unknown"


def typst_version(executable: str) -> str:
    result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30)
    return parse_version(result.stdout)


def typst_command() -> str:
    executable = shutil.which("typst")
    if executable is None:
        raise TypstNotFound(f"typst is not on PATH; install it with: {INSTALL_COMMAND}")
    found = typst_version(executable)
    if found != TYPST_VERSION:
        raise TypstVersionError(f"typst {found} is installed; docla needs typst {TYPST_VERSION}")
    return executable


def typst_env() -> dict[str, str]:
    env = dict(os.environ)
    env["SOURCE_DATE_EPOCH"] = "0"
    return env


def run_typst(args: Sequence[str], root: Path, font_paths: Sequence[Path] = ()) -> str:
    command = [typst_command(), *args, "--root", str(root), "--ignore-system-fonts"]
    for path in font_paths:
        command += ["--font-path", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, env=typst_env())
    if result.returncode != 0:
        raise TypstCompileError(result.stderr)
    return result.stdout


def compile_pdf(main: Path, root: Path, output: Path, font_paths: Sequence[Path] = ()) -> None:
    try:
        run_typst(["compile", str(main), str(output)], root, font_paths)
    except TypstCompileError:
        output.unlink(missing_ok=True)
        raise
