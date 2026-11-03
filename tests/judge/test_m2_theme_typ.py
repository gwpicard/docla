# Intent: render_theme_typ generates theme.typ from theme tokens and assemble renders with the theme's own fonts.
import importlib
import json
import re
from pathlib import Path

import pytest

from docla.model import Document, Item, Section
from docla.render.kit import lib_dir
from docla.render.typst import TypstCompileError, compile_pdf, run_typst


def _optional(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if module_name != name and not module_name.startswith(name + ".") and not name.startswith(module_name + "."):
            raise
        return None


typst_module = _optional("docla.theme.typst")
theme_module = _optional("docla.theme")
compose_module = _optional("docla.render.compose")

ROLES = {
    "ink": "#1A1A1A",
    "ink-soft": "#4A4F55",
    "muted": "#6B6B6B",
    "surface": "#FFFFFF",
    "surface-alt": "#F2F3F4",
    "accent": "#2F5D8A",
    "hairline": "#D5D8DB",
    "on-dark": "#FFFFFF",
    "dark": "#1A1A1A",
}
CHART = ["#8A9096", "#7A4DFF", "#00A37A", "#E0A100", "#C2410C", "#6B7280"]
ALL_HEX = {value.lower() for value in ROLES.values()} | {value.lower() for value in CHART}
HEX_LITERAL = re.compile(r"(?<![0-9A-Za-z])#[0-9A-Fa-f]{6}(?![0-9A-Za-z])")


def _require_interface() -> None:
    assert theme_module is not None and hasattr(theme_module, "neutral_theme"), "docla.theme.neutral_theme must exist"
    assert typst_module is not None and hasattr(typst_module, "render_theme_typ"), (
        "docla.theme.typst.render_theme_typ must exist"
    )
    assert compose_module is not None and hasattr(compose_module, "assemble"), (
        "docla.render.compose.assemble must exist"
    )
    assert hasattr(compose_module, "font_paths"), "docla.render.compose.font_paths must exist"


def _document() -> Document:
    return Document(
        front={},
        format="slides",
        sections=[
            Section(id="s1", intent="statement", title="One clear claim"),
            Section(
                id="s2",
                intent="bullets",
                title="Two points",
                items=[Item(head="First", body="alpha body"), Item(body="beta body")],
            ),
        ],
    )


def _assemble_themed(tmp_path: Path) -> tuple[Path, Path]:
    comp = compose_module.compose(_document())
    dest = tmp_path / "render"
    main = compose_module.assemble(comp, dest, theme=theme_module.neutral_theme())
    return main, dest


def _compile_source(dest: Path, name: str, source: str) -> Path:
    main = dest / name
    main.write_text('#import "/lib/theme.typ": *\n' + source + "\n")
    out = dest / (name + ".pdf")
    compile_pdf(main, dest, out, compose_module.font_paths(dest))
    return out


def _probe(dest: Path, expression: str):
    main = dest / "probe.typ"
    main.write_text('#import "/lib/theme.typ": *\n' + f"#metadata({expression}) <probe>\n")
    output = run_typst(
        ["eval", "query(<probe>).first().value", "--in", str(main)], dest, compose_module.font_paths(dest)
    )
    return json.loads(output)


def test_D1_theme_typ_holds_every_role_and_family_name():
    _require_interface()
    text = typst_module.render_theme_typ(theme_module.neutral_theme())
    for role, value in ROLES.items():
        assert role in text
        assert value.lower() in text.lower()
    assert "Inter" in text
    assert "Source Serif 4" in text


def test_D1_every_hex_literal_is_a_token_colour():
    _require_interface()
    text = typst_module.render_theme_typ(theme_module.neutral_theme())
    found = {match.lower() for match in HEX_LITERAL.findall(text)}
    assert found, "the generated module must carry the token colours"
    assert found <= ALL_HEX, f"colours not in the tokens: {sorted(found - ALL_HEX)}"


def test_D2_slides_pdf_uses_only_theme_fonts(tmp_path: Path):
    _require_interface()
    from docla.facts.pdf import PdfPlumberFacts

    main, dest = _assemble_themed(tmp_path)
    assert compose_module.font_paths(dest) == [dest / "fonts"]
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, dest, pdf, compose_module.font_paths(dest))
    words = [word for page in PdfPlumberFacts().extract(pdf) for word in page.words]
    assert words
    for word in words:
        assert "Inter" in word.font or "SourceSerif4" in word.font, f"{word.text!r} uses {word.font}"


def test_D3_every_word_colour_is_a_theme_role(tmp_path: Path):
    _require_interface()
    from docla.facts.pdf import PdfPlumberFacts

    main, dest = _assemble_themed(tmp_path)
    pdf = tmp_path / "out.pdf"
    compile_pdf(main, dest, pdf, compose_module.font_paths(dest))
    words = [word for page in PdfPlumberFacts().extract(pdf) for word in page.words]
    assert words
    allowed = {value.lower() for value in ROLES.values()}
    for word in words:
        assert word.colour is not None and word.colour.lower() in allowed, f"{word.text!r} is {word.colour}"


def test_D4_valid_calls_compile(tmp_path: Path):
    _require_interface()
    _, dest = _assemble_themed(tmp_path)
    out = _compile_source(
        dest,
        "ok.typ",
        '#show: page-setup.with("doc")\n#text(..type-style("doc", "body"), fill: colour("ink"))[fine]',
    )
    assert out.exists()


@pytest.mark.parametrize(
    ("source", "name"),
    [
        ('#text(fill: colour("nope"))[x]', "nope"),
        ('#text(..type-style("slides", "nope"))[x]', "nope"),
        ('#show: page-setup.with("poster")\nx', "poster"),
    ],
)
def test_D4_unknown_names_fail_to_compile_and_are_named(tmp_path: Path, source: str, name: str):
    _require_interface()
    _, dest = _assemble_themed(tmp_path)
    with pytest.raises(TypstCompileError) as raised:
        _compile_source(dest, "bad.typ", source)
    assert name in str(raised.value)


def test_D5_doc_body_style_and_space_values(tmp_path: Path):
    _require_interface()
    _, dest = _assemble_themed(tmp_path)
    values = _probe(
        dest,
        '(size: type-style("doc", "body").size.pt(), font: type-style("doc", "body").font, space: space(3).pt())',
    )
    assert values == {"size": 11.0, "font": "Inter", "space": 16.0}


def test_D6_assemble_without_theme_keeps_the_stub(tmp_path: Path):
    _require_interface()
    comp = compose_module.compose(_document())
    dest = tmp_path / "render"
    compose_module.assemble(comp, dest)
    assert (dest / "lib" / "theme.typ").read_bytes() == (lib_dir() / "theme.typ").read_bytes()
    assert compose_module.font_paths(dest) == []
