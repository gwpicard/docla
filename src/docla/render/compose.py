import shutil
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from docla.model import Document, Format, Item, Section
from docla.render.chooser import Chooser, ChooserError, load_chooser
from docla.render.kit import components_dir, lib_dir
from docla.theme import Theme
from docla.theme.typst import render_theme_typ

M1_COMPONENTS: dict[tuple[Format, str], str] = {
    ("slides", "statement"): "statement",
    ("slides", "bullets"): "bullets",
    ("doc", "body"): "body",
    ("doc", "callout"): "callout",
}


class ComposeError(ValueError):
    pass


class ComposedSection(BaseModel):
    id: str
    component: str
    props: dict[str, Any]


class Composition(BaseModel):
    format: Format
    sections: list[ComposedSection]


@cache
def default_chooser() -> Chooser:
    """Return the packaged chooser, read once."""
    return load_chooser()


def _chosen(section: Section, fmt: Format, chooser: Chooser, index: int, total: int) -> str | None:
    if section.component in chooser.names(fmt):
        return section.component
    return chooser.choose(section, fmt, index, total)


def component_for(section: Section, fmt: Format, index: int = 0, total: int = 1) -> str | None:
    """Return the component that draws `section` at `index` of `total` in format `fmt`, or None when there is none."""
    try:
        return _chosen(section, fmt, default_chooser(), index, total)
    except ChooserError:
        return None


def _component(section: Section, fmt: Format, chooser: Chooser, index: int, total: int) -> str:
    try:
        component = _chosen(section, fmt, chooser, index, total)
    except ChooserError as error:
        raise ComposeError(f"section {section.id}: {error}") from error
    if component is None:
        raise ComposeError(f"section {section.id}: prose sections are not supported yet")
    return component


def _item_props(item: Item) -> dict[str, Any]:
    return {"head": item.head or "", "body": item.body, "cites": [c.key for c in item.citations]}


def _compose_section(section: Section, fmt: Format, chooser: Chooser, index: int, total: int) -> ComposedSection:
    if not section.id:
        raise ComposeError(f"section {index + 1} (intent {section.intent!r}) has no id")
    props = {
        "id": section.id,
        "title": section.title or "",
        "items": [_item_props(item) for item in section.items],
        "paragraphs": list(section.paragraphs),
        "source_line": section.source_line or "",
    }
    component = _component(section, fmt, chooser, index, total)
    return ComposedSection(id=section.id, component=component, props=props)


def compose(doc: Document, chooser: Chooser | None = None) -> Composition:
    """Map each section of `doc` to a component and its props, in order, using `chooser` or the default one."""
    chooser = default_chooser() if chooser is None else chooser
    total = len(doc.sections)
    sections = [_compose_section(section, doc.format, chooser, i, total) for i, section in enumerate(doc.sections)]
    return Composition(format=doc.format, sections=sections)


def _main_typ(comp: Composition) -> str:
    lines = ['#import "/lib/theme.typ": colour, page-setup']
    for name in dict.fromkeys(s.component for s in comp.sections):
        lines.append(f'#import "/components/{name}.typ": {name}')
    lines += [
        "",
        f'#show: page-setup.with("{comp.format}")',
        '#set text(fill: colour("ink"))',
        "",
        '#let comp = json("/composition.json")',
    ]
    for i, section in enumerate(comp.sections):
        if i > 0 and comp.format == "slides":
            lines.append("#pagebreak()")
        lines.append(f"#{section.component}(comp.sections.at({i}).props)")
    return "\n".join(lines) + "\n"


def _apply_theme(theme: Theme, dest: Path) -> None:
    (dest / "lib" / "theme.typ").write_text(render_theme_typ(theme))
    shutil.copytree(theme.fonts_dir, dest / "fonts")


def font_paths(dest: Path) -> list[Path]:
    """Return the font folders of the render folder at `dest`, for Typst's `--font-path`."""
    fonts = dest / "fonts"
    return [fonts] if fonts.is_dir() else []


def assemble(comp: Composition, dest: Path, *, theme: Theme | None = None) -> Path:
    """Write a render folder at `dest` that Typst compiles; return the path of `main.typ`.

    With a theme, `lib/theme.typ` is generated from its tokens and its fonts are copied to `fonts/`.
    """
    if dest.exists():
        raise FileExistsError(f"render folder already exists: {dest}")
    shutil.copytree(lib_dir(), dest / "lib")
    if theme is not None:
        _apply_theme(theme, dest)
    shutil.copytree(components_dir(), dest / "components")
    (dest / "composition.json").write_text(comp.model_dump_json())
    main = dest / "main.typ"
    main.write_text(_main_typ(comp))
    return main
