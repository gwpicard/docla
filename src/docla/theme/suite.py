"""Run the checks that exercise a theme."""

import contextlib
import io
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from docla.doctypes import DoctypeError, library_dir, load_doctype, packaged_dir, theme_doctypes_dir
from docla.model import Document, Section
from docla.render.chooser import Chooser, ChooserError, default_path, load_chooser
from docla.render.components import all_manifests
from docla.render.marks import SectionMark
from docla.render.swatch import swatch
from docla.testing.golden import _fixture_assets
from docla.theme import Theme, ThemeError
from docla.theme.rules import load_theme_rules


def _rules(theme: Theme) -> str:
    try:
        load_theme_rules(theme)
    except ThemeError as error:
        return f"fail rules: {error}"
    return "ok rules"


def _chooser(theme: Theme) -> tuple[str, Chooser | None]:
    path = theme.root / "chooser.yaml"
    try:
        chooser = load_chooser(path if path.exists() else default_path(), manifests=all_manifests())
    except ChooserError as error:
        return f"fail chooser: {error}", None
    return "ok chooser", chooser


def _doctypes(theme: Theme, chooser: Chooser | None) -> str:
    if chooser is None:
        return "fail doctypes: chooser did not load"
    for path in (
        *sorted(packaged_dir().glob("*.yaml")),
        *sorted(library_dir().glob("*.yaml")),
        *sorted(theme_doctypes_dir(theme.root).glob("*.yaml")),
    ):
        try:
            load_doctype(path, chooser)
        except DoctypeError as error:
            return f"fail doctypes: {path.name}: {error}"
    return "ok doctypes"


def _fixtures(theme: Theme, out: Path) -> str:
    for name, manifest in all_manifests().items():
        if not manifest.fixture:
            continue
        try:
            data = yaml.safe_load(Path(manifest.fixture).read_text(encoding="utf-8"))
            section = Section.model_validate(data)
            if not section.id:
                raise ValueError("fixture has no section id")
            workdir = out / "fixtures" / name
            workdir.mkdir(parents=True, exist_ok=True)
            doc = Document(front={}, format=manifest.format, sections=[section])
            facts = swatch(doc, section.id, workdir, theme, assets=_fixture_assets(section, workdir)).facts
            if not any(isinstance(mark, SectionMark) and mark.id == section.id for mark in facts.marks):
                raise ValueError("section mark missing")
        except Exception as error:
            return f"fail fixtures: {name}: {error}"
    return "ok fixtures"


def _gold(theme: Theme, out: Path) -> str:
    from docla.cli import _BuildFailed, _check

    folder = theme.root / "exemplars" / "gold"
    if not folder.is_dir():
        return "ok gold (none)"
    for path in sorted(folder.glob("*.md")):
        workdir = out / "gold" / path.stem
        workdir.mkdir(parents=True, exist_ok=True)
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                result = _check(path, workdir, theme, final=True)
        except _BuildFailed as error:
            return f"fail gold: {path.name}: {error}"
        if result:
            errors = [line for line in output.getvalue().splitlines() if line.startswith("error ")]
            return f"fail gold: {path.name}: {'; '.join(errors)}"
    return "ok gold"


def theme_test(theme: Theme, out: Path) -> list[str]:
    """Return the results of the theme suite in execution order."""
    rules = _rules(theme)
    chooser_line, chooser = _chooser(theme)
    doctypes = _doctypes(theme, chooser)
    fixtures = _fixtures(theme, out)
    gold = _gold(theme, out) if rules == "ok rules" else "fail gold: rules did not load"
    lines = [rules, chooser_line, doctypes, fixtures, gold]
    return [" ".join(line.split()) if line.startswith("fail ") else line for line in lines]
