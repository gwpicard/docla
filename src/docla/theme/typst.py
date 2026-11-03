from docla.theme.models import Margins, Page, Theme, TypeRole, TypeScale

HEADER = "// Generated from the theme's tokens by docla.theme.typst. Do not edit.\n"

FUNCTIONS = """
#let colour(name) = {
  if name not in tokens {
    panic("unknown colour role: " + repr(name) + "; the theme has " + tokens.keys().join(", "))
  }
  rgb(tokens.at(name))
}

#let type-style(format, role) = {
  if format not in type-scale {
    panic("unknown type format: " + repr(format) + "; the theme has " + type-scale.keys().join(", "))
  }
  let roles = type-scale.at(format)
  if role not in roles {
    panic("unknown type role: " + repr(role) + " in " + format + "; the theme has " + roles.keys().join(", "))
  }
  roles.at(role)
}

#let space(n) = space-unit * space-scale.at(n)

#let page-setup(format, body) = {
  if format not in pages {
    panic("unknown page format: " + repr(format) + "; the theme has " + formats.join(", "))
  }
  let p = pages.at(format)
  set page(width: p.width, height: p.height, margin: p.margin)
  set page(columns: p.columns) if p.columns > 1
  set text(font: text-font, ..p.body-text, fill: colour("ink"))
  body
}
"""


def render_theme_typ(theme: Theme) -> str:
    """Return a Typst module that gives components the theme's resolved tokens."""
    tokens = theme.tokens
    families = {key: family.name for key, family in tokens.type.families.items()}
    lines = [
        HEADER,
        f"#let tokens = {_dict({name: _str(value) for name, value in tokens.colour.roles.items()})}",
        f"#let chart = {_dict({name: _array([_str(c) for c in cs]) for name, cs in tokens.colour.chart.items()})}",
        f"#let formats = {_array([_str(fmt) for fmt in theme.info.formats])}",
        f"#let text-font = {_str(families.get('text', ''))}",
        f"#let type-scale = {_dict({fmt: _scale(scale, families) for fmt, scale in tokens.type.scale.items()})}",
        f"#let space-unit = {_pt(tokens.spacing.unit)}",
        f"#let space-scale = {_array([repr(float(step)) for step in tokens.spacing.scale])}",
        f"#let pages = {_dict({fmt: _page(page, tokens.type.scale.get(fmt)) for fmt, page in tokens.pages.items()})}",
    ]
    return "\n".join(lines) + "\n" + FUNCTIONS


def _str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _pt(value: float) -> str:
    return f"{float(value)!r}pt"


def _dict(entries: dict[str, str]) -> str:
    if not entries:
        return "(:)"
    return "(" + ", ".join(f"{_str(key)}: {value}" for key, value in entries.items()) + ")"


def _array(items: list[str]) -> str:
    if len(items) == 1:
        return f"({items[0]},)"
    return "(" + ", ".join(items) + ")"


def _style(role: TypeRole, families: dict[str, str]) -> str:
    return f"(font: {_str(families[role.family])}, size: {_pt(role.size)}, weight: {role.weight})"


def _scale(scale: TypeScale, families: dict[str, str]) -> str:
    return _dict({name: _style(role, families) for name, role in scale.roles.items()})


def _margin(margin: Margins) -> str:
    return (
        f"(top: {_pt(margin.top)}, right: {_pt(margin.right)}, bottom: {_pt(margin.bottom)}, left: {_pt(margin.left)})"
    )


def _body_text(scale: TypeScale | None) -> str:
    body = scale.roles.get("body") if scale else None
    return f"(size: {_pt(body.size)})" if body else "(:)"


def _page(page: Page, scale: TypeScale | None) -> str:
    return (
        f"(width: {_pt(page.width)}, height: {_pt(page.height)}, margin: {_margin(page.margin)}, "
        f"columns: {page.columns}, body-text: {_body_text(scale)})"
    )
