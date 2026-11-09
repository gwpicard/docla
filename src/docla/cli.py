import argparse
import asyncio
import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import TypeAdapter

from docla import __version__
from docla.checks.catalogue import all_rules, document_rules
from docla.checks.engine import CheckContext, run_checks
from docla.config import default_config_text
from docla.facts.layout import layout_facts
from docla.facts.raster import PdfiumRasteriser
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
    print(f"anthropic key: {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'missing'}")
    return 0 if python_ok else 1


def _init(directory: Path) -> int:
    path = directory / "docla.toml"
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(default_config_text())
    except FileExistsError:
        print(f"{path} already exists", file=sys.stderr)
        return 1
    (directory / "sources").mkdir(exist_ok=True)
    print(path)
    return 0


class _Built(NamedTuple):
    doc: Document
    findings: list[Finding]
    render: Path
    main: Path
    pdf: Path
    comp: Composition


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
    return _Built(doc, findings, render, main, pdf, comp)


def _render(file: Path, out: Path, theme: Theme) -> _Built:
    doc, findings = _parse(file)
    try:
        comp = compose(doc, assets=[file.parent / "assets", theme.root / "assets"])
    except ComposeError as error:
        raise _BuildFailed(str(error)) from error
    return _draw(file, out, doc, findings, comp, theme)


def _line(finding: Finding) -> str:
    return f"{finding.severity} {finding.rule_id} {finding.section_id or '-'} {finding.message}"


def _build(file: Path, out: Path, theme: Theme, *, final: bool = False) -> int:
    built = _render(file, out, theme)
    print(built.pdf)
    return _final_build(file, out, theme, built) if final else 0


def _final_build(file: Path, out: Path, theme: Theme, built: _Built) -> int:
    from docla.loop.look import LookContext, look
    from docla.store import write_version
    from docla.store.gate import ship_gate

    try:
        rules = all_rules() + load_theme_rules(theme)
    except ThemeError as error:
        raise _BuildFailed(str(error)) from error
    result = asyncio.run(
        look(
            built.pdf,
            built.comp,
            LookContext(
                doc=built.doc,
                theme=theme,
                main=built.main,
                project=file.parent,
                workdir=out,
                rules=rules,
                critic=None,
                final=True,
                assets=[file.parent / "assets", theme.root / "assets"],
            ),
        )
    )
    version = write_version(
        file,
        built.doc,
        built.comp,
        built.pdf,
        result.facts,
        built.findings + result.findings,
        result.pngs,
        None,
        theme=theme,
        final=True,
        look=result.record(),
    )
    print(version.path)
    return _gate_report(ship_gate(version))


def _gate_report(reasons: list[str]) -> int:
    for reason in reasons:
        print(f"not ready: {reason}")
    if not reasons:
        print("gate: passed")
    return int(bool(reasons))


def _ready(args: argparse.Namespace) -> int:
    from docla.store import load_version
    from docla.store.gate import mark_ready

    if (args.force and (args.reason is None or not args.reason.strip())) or (
        args.reason is not None and not args.force
    ):
        print("--reason requires --force and must be non-blank when forced", file=sys.stderr)
        return 2
    try:
        version = load_version(args.version_dir)
        reasons = mark_ready(version, force=args.force, reason=args.reason)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2
    if reasons and not args.force:
        for reason in reasons:
            print(f"not ready: {reason}")
        return 1
    print(f"ready (forced: {args.reason})" if args.force else "ready")
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
        return _report(
            file, out, parsed + run_checks(rules, CheckContext(doc, theme=theme, final=final, assets=assets))
        )
    built = _draw(file, out, doc, parsed, comp, theme)
    facts = layout_facts(built.pdf, built.main, built.render, font_paths=font_paths(built.render))
    pages_png = PdfiumRasteriser().render(built.pdf, out / "pages")
    ctx = CheckContext(
        built.doc,
        facts,
        read_tokens(built.render),
        theme=theme,
        composition=comp,
        final=final,
        assets=assets,
        pages_png=pages_png,
    )
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
    if name in ("build", "check"):
        command.add_argument("--final", action="store_true", help="treat the working file as a final build")
    if name == "check":
        command.add_argument("--outline", action="store_true", help="check conformance to the doctype outline")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docla")
    parser.add_argument("--version", action="version", version=f"docla {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="report what is installed and what is missing")
    init = subparsers.add_parser("init", help="initialise a project")
    init.add_argument("directory", type=Path, help="project folder")
    _add_file_command(subparsers, "build", "render a working file to PDF")
    _add_file_command(subparsers, "check", "render a working file and report what the M1 rules find")
    _add_file_command(subparsers, "write", "prepare and draft a working file")
    ready = subparsers.add_parser("ready", help="mark a version ready")
    ready.add_argument("version_dir", type=Path)
    ready.add_argument("--force", action="store_true")
    ready.add_argument("--reason")
    write = subparsers.choices["write"]
    write.add_argument("--approve", action="store_true")
    write.add_argument("--yes", action="store_true")
    theme = subparsers.add_parser("theme", help="work with themes")
    theme_commands = theme.add_subparsers(dest="theme_command", required=True)
    test = theme_commands.add_parser("test", help="test a theme")
    test.add_argument("--theme", type=Path, default=None, help="theme folder")
    evaluation = subparsers.add_parser("eval", help="run evaluations")
    eval_commands = evaluation.add_subparsers(dest="eval_command", required=True)
    heal = eval_commands.add_parser("heal", help="run the heal evaluation")
    heal.add_argument("--live", action="store_true")
    heal.add_argument("--cases", type=Path, default=Path("tests/fixtures/heal-eval"))
    heal.add_argument("--out", type=Path, default=Path("evals/RESULTS.md"))
    heal.add_argument("--theme", type=Path, default=None)
    critic = eval_commands.add_parser("critic", help="run the critic evaluation")
    critic.add_argument("--live", action="store_true")
    critic.add_argument("--cases", type=Path, default=Path("tests/fixtures/critic-eval"))
    critic.add_argument("--out", type=Path, default=Path("evals/CRITIC.md"))
    critic.add_argument("--calibration", type=Path, default=None)
    critic.add_argument("--theme", type=Path, default=None)
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
        return _build(args.file, out, _theme(args.theme), final=args.final)
    except _BuildFailed as error:
        print(error, file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "doctor":
        return _doctor()
    if args.command == "init":
        return _init(args.directory)
    if args.command == "ready":
        return _ready(args)
    if args.command == "write":
        return _write(args)
    if args.command in FILE_COMMANDS:
        return _run_file_command(args)
    if args.command == "theme":
        return _run_theme_test(args.theme)
    if args.command == "eval":
        return _heal(args) if args.eval_command == "heal" else _critic_eval(args)
    return 1


def _critic_eval(args: argparse.Namespace) -> int:
    if args.live and os.environ.get("DOCLA_LIVE") != "1":
        print("Live evaluation requires DOCLA_LIVE=1", file=sys.stderr)
        return 2
    from docla.evals.critic import ScriptedCritic, calibration_yaml, load_cases, render_results, run_critic

    cases = load_cases(args.cases)
    theme = _theme(args.theme)
    verdict = _live_critic(args.out, theme) if args.live else ScriptedCritic()
    report = asyncio.run(run_critic(cases, verdict))
    report.mode = "live" if args.live else "offline"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_results(report))
    calibration = args.calibration or (theme.root / "rubric/calibration.yaml" if args.live else None)
    if calibration is not None:
        calibration.parent.mkdir(parents=True, exist_ok=True)
        calibration.write_text(calibration_yaml(report))
    return 0


def _live_critic(out: Path, theme: Theme) -> Any:
    from PIL import Image

    from docla.agents.critic import CriticImage, Region, critique
    from docla.agents.ledger import Ledger
    from docla.agents.scheduler import Scheduler
    from docla.config import load_project_config
    from docla.model import Box
    from docla.theme.rubric import load_rubric
    from docla.write import ScheduledClaude, live_transport, role_models

    config = load_project_config(Path.cwd())
    ledger = Ledger(out.parent / "critic-ledger.jsonl", config.prices, config.budget.max_usd_per_document)
    claude = ScheduledClaude(
        live_transport(), ledger, role_models(config), scheduler=Scheduler(config.loop.max_parallel_sections)
    )
    rubric = load_rubric(theme)

    async def verdict(case: Any, run: int) -> str:
        with Image.open(case.crop) as image:
            width, height = image.size
        item = rubric.get(case.rubric_id)
        findings = await critique(
            claude,
            [CriticImage(case.crop, 1, width, height, "crop")],
            [item],
            [],
            [Region("crop", None, 1, Box(x=0, y=0, w=width, h=height))],
            format=(item.applies.formats or ["slides"])[0],
        )
        return "fail" if any(f.rule_id == case.rubric_id for f in findings) else "pass"

    return verdict


def _heal(args: argparse.Namespace) -> int:
    if args.live and os.environ.get("DOCLA_LIVE") != "1":
        print("Live evaluation requires DOCLA_LIVE=1", file=sys.stderr)
        return 2
    from docla.evals.heal import HealCase, ScriptedWriter, load_cases, render_results, run_heal
    from docla.loop.micro import SectionWriter

    cases = load_cases(args.cases)
    theme = _theme(args.theme)

    def spent() -> float:
        return 0.0

    writer_for: Callable[[HealCase], SectionWriter] = ScriptedWriter
    if args.live:
        from docla.agents.ledger import Ledger
        from docla.agents.scheduler import Scheduler
        from docla.config import load_project_config
        from docla.write import ClaudeWriter, ScheduledClaude, live_transport, role_models

        config = load_project_config(Path.cwd())
        ledger = Ledger(args.out.parent / "heal-ledger.jsonl", config.prices, config.budget.max_usd_per_document)
        claude = ScheduledClaude(
            live_transport(), ledger, role_models(config), scheduler=Scheduler(config.loop.max_parallel_sections)
        )

        class LiveWriter(ClaudeWriter):
            def __init__(self, case: Any) -> None:
                super().__init__(claude, [], theme, case.document)
                self.case = case

            async def draft(self, job: Any) -> Any:
                return self.case.document.sections[0]

        writer_for = LiveWriter

        def spent() -> float:
            return ledger.total

    with tempfile.TemporaryDirectory() as directory:
        report = asyncio.run(run_heal(cases, writer_for=writer_for, theme=theme, workdir=Path(directory), spent=spent))
    report.mode = "live" if args.live else "offline"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_results(report))
    return 0 if report.gate else 1


def _write(args: argparse.Namespace) -> int:
    from docla.agents.cassette import CassetteMiss
    from docla.agents.client import AgentInvalid, AgentRefused, AgentTruncated
    from docla.agents.ledger import Ledger
    from docla.agents.scheduler import Scheduler
    from docla.config import load_project_config
    from docla.write import ScheduledClaude, claude_agents, role_models, run_write, transport_for

    project = args.file.parent
    config = load_project_config(project)
    ledger = Ledger(
        project / ".docla" / "write" / args.file.stem / "ledger.jsonl",
        config.prices,
        config.budget.max_usd_per_document,
    )
    try:
        theme = _theme(args.theme)
        claude = ScheduledClaude(
            transport_for(project), ledger, role_models(config), scheduler=Scheduler(config.loop.max_parallel_sections)
        )
        return asyncio.run(
            run_write(
                args.file,
                agents=claude_agents(claude, theme, config=config),
                theme=theme,
                out=_out_dir(args.file, args.out),
                approve=args.approve,
                yes=args.yes,
                spent=lambda: ledger.total,
            )
        )
    except CassetteMiss as error:
        print(f"{project / '.docla' / 'cassette.json'}: {error}; set DOCLA_LIVE=1 for live calls", file=sys.stderr)
    except (AgentRefused, AgentTruncated, AgentInvalid, _BuildFailed) as error:
        print(error, file=sys.stderr)
    return 2


def _run_theme_test(folder: Path | None) -> int:
    from docla.theme.suite import theme_test

    try:
        theme = _theme(folder)
    except _BuildFailed as error:
        print(error, file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as directory:
        lines = theme_test(theme, Path(directory))
    for line in lines:
        print(line)
    return int(any(line.startswith("fail ") for line in lines))


if __name__ == "__main__":
    sys.exit(main())
