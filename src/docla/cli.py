import argparse
import shutil
import sys
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import TypeAdapter

from docla import __version__
from docla.checks.catalogue import all_rules, document_rules
from docla.checks.engine import CheckContext, run_checks
from docla.facts.layout import layout_facts
from docla.model import Document, Finding
from docla.render.compose import ComposeError, Composition, assemble, compose, font_paths
from docla.render.kit import read_tokens
from docla.render.typst import INSTALL_COMMAND, TYPST_VERSION, TypstError, compile_pdf, typst_version
from docla.source.parser import parse
from docla.theme import Theme, ThemeError, load_theme, neutral_theme
from docla.theme.rules import load_theme_rules

MIN_PYTHON = (3, 12)


def _python_line() -> tuple[str, bool]:
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) < MIN_PYTHON:
        return f"python: {version} (needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or later)", False
    return f"python: {version}", True


def _typst_lines() -> list[str]:
    executable = shutil.which("typst")
    if executable is None:
        return ["typst: missing", f"install: {INSTALL_COMMAND}"]
    found = typst_version(executable)
    if found != TYPST_VERSION:
        return [f"typst: {found}", f"needs: typst {TYPST_VERSION}"]
    return [f"typst: {found}"]


def _doctor() -> int:
    python_line, python_ok = _python_line()
    print(python_line)
    for line in _typst_lines():
        print(line)
    return 0 if python_ok else 1


class _Built(NamedTuple):
    doc: Document
    findings: list[Finding]
    render: Path
    main: Path
    pdf: Path


class _BuildFailed(Exception):
    pass


def _out_dir(file: Path, out: Path | None) -> Path:
    return out if out is not None else file.parent / "build"


def _parse(file: Path) -> tuple[Document, list[Finding]]:
    doc, findings = parse(file.read_text())
    errors = [f for f in findings if f.severity == "error"]
    if errors:
        raise _BuildFailed("\n".join(_line(f) for f in errors))
    return doc, findings


def _draw(file: Path, out: Path, doc: Document, findings: list[Finding], comp: Composition, theme: Theme) -> _Built:
    render = out / "render"
    if render.exists():
        shutil.rmtree(render)
    main = assemble(comp, render, theme=theme)
    pdf = out / f"{file.stem}.pdf"
    try:
        compile_pdf(main, render, pdf, font_paths(render))
    except TypstError as error:
        raise _BuildFailed(str(error)) from error
    return _Built(doc, findings, render, main, pdf)


def _render(file: Path, out: Path, theme: Theme) -> _Built:
    doc, findings = _parse(file)
    try:
        comp = compose(doc, assets=[file.parent / "assets", theme.root / "assets"])
    except ComposeError as error:
        raise _BuildFailed(str(error)) from error
    return _draw(file, out, doc, findings, comp, theme)


def _line(finding: Finding) -> str:
    return f"{finding.severity} {finding.rule_id} {finding.section_id or '-'} {finding.message}"


def _build(file: Path, out: Path, theme: Theme) -> int:
    built = _render(file, out, theme)
    print(built.pdf)
    return 0


def _check(file: Path, out: Path, theme: Theme, *, final: bool = False, outline: bool = False) -> int:
    doc, parsed = _parse(file)
    try:
        rules = all_rules() + load_theme_rules(theme)
        if outline:
            rules += document_rules()
    except ThemeError as error:
        raise _BuildFailed(str(error)) from error
    assets = [file.parent / "assets", theme.root / "assets"]
    try:
        comp = compose(doc, assets=assets)
    except ComposeError:
        # Without layout facts the engine runs only the source tier.
        return _report(file, out, parsed + run_checks(rules, CheckContext(doc, theme=theme, final=final, assets=assets)))
    built = _draw(file, out, doc, parsed, comp, theme)
    facts = layout_facts(built.pdf, built.main, built.render, font_paths=font_paths(built.render))
    ctx = CheckContext(built.doc, facts, read_tokens(built.render), theme=theme, composition=comp, final=final, assets=assets)
    return _report(file, out, built.findings + run_checks(rules, ctx))


def _report(file: Path, out: Path, findings: list[Finding]) -> int:
    report = TypeAdapter(list[Finding]).dump_json(findings, indent=2)
    (out / f"{file.stem}.findings.json").write_bytes(report)
    for finding in findings:
        print(_line(finding))
    if not findings:
        print("no findings")
    return 1 if any(f.severity == "error" for f in findings) else 0


def _add_file_command(subparsers: Any, name: str, help: str) -> None:
    command = subparsers.add_parser(name, help=help)
    command.add_argument("file", type=Path, help="the working file")
    command.add_argument("--out", type=Path, default=None, help="output folder (default: build beside the file)")
    command.add_argument("--theme", type=Path, default=None, help="theme folder (default: the neutral theme)")
    if name == "check":
        command.add_argument("--final", action="store_true", help="check the working file as a final build")
        command.add_argument("--outline", action="store_true", help="check conformance to the doctype outline")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docla")
    parser.add_argument("--version", action="version", version=f"docla {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="report what is installed and what is missing")
    _add_file_command(subparsers, "build", "render a working file to PDF")
    _add_file_command(subparsers, "check", "render a working file and report what the M1 rules find")
    return parser


FILE_COMMANDS = {"build": _build, "check": _check}


def _theme(folder: Path | None) -> Theme:
    try:
        return neutral_theme() if folder is None else load_theme(folder)
    except ThemeError as error:
        raise _BuildFailed(str(error)) from error


def _run_file_command(args: argparse.Namespace) -> int:
    out = _out_dir(args.file, args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == "check":
            return _check(args.file, out, _theme(args.theme), final=args.final, outline=args.outline)
        return FILE_COMMANDS[args.command](args.file, out, _theme(args.theme))
    except _BuildFailed as error:
        print(error, file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    if args.command in FILE_COMMANDS:
        return _run_file_command(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
