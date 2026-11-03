# Intent: load a theme's theme.yaml and tokens.yaml into validated models and refuse fonts without a licence record.
import copy
import importlib.util
from pathlib import Path

import pytest
import yaml

try:
    from docla.theme.loader import ThemeError, load_theme
    from docla.theme.models import to_pt
except ImportError as error:
    name = str(error.name)
    if name != "docla.theme" and not name.startswith("docla.theme."):
        raise
    ThemeError = None
    load_theme = None
    to_pt = None

BASE_TOKENS = {
    "schema": 1,
    "colour": {
        "roles": {"ink": "#1a1a1a", "paper": "#ffffff", "accent": "#0a5fd8"},
        "chart": {"categorical": ["#0a5fd8", "#d85a0a"]},
        "usage": {"text": ["ink"], "fill": ["paper", "accent"], "stroke": ["ink"]},
        "contrast_min": 4.5,
    },
    "type": {
        "families": {
            "sans": {"name": "Test Sans", "files": ["Sans-Regular.ttf"]},
        },
        "scale": {
            "slides": {
                "body": {"family": "sans", "size": 24, "weight": 400, "leading": 30},
                "min_size": 18,
            },
            "doc": {
                "body": {"family": "sans", "size": 10.5},
                "min_size": 8,
            },
        },
    },
    "pages": {
        "slides": {
            "width": 960,
            "height": 540,
            "margin": {"top": 40, "right": 40, "bottom": 40, "left": 40},
        },
        "doc": {
            "size": "a4",
            "margin": {"top": "20mm", "right": "1in", "bottom": 50, "left": "12pt"},
        },
    },
    "spacing": {"unit": 4, "scale": [4, 8, 16]},
}

BASE_INFO = {"name": "Test", "version": "1.0", "formats": ["slides", "doc"]}

LICENCE_LINE = "file: Sans-Regular.ttf\nfamily: Test Sans\nlicence: OFL-1.1\n"


def build_theme(root: Path, tokens=None, info=None, licences=LICENCE_LINE, fonts=("Sans-Regular.ttf",)):
    root.mkdir(parents=True, exist_ok=True)
    (root / "theme.yaml").write_text(yaml.safe_dump(info or BASE_INFO))
    if tokens is not False:
        (root / "tokens.yaml").write_text(yaml.safe_dump(tokens or BASE_TOKENS))
    fonts_dir = root / "fonts"
    fonts_dir.mkdir(exist_ok=True)
    for font in fonts:
        (fonts_dir / font).write_bytes(b"placeholder")
    if licences is not None:
        (fonts_dir / "LICENSES.txt").write_text(licences)
    return root


def tokens_with(mutate):
    tokens = copy.deepcopy(BASE_TOKENS)
    mutate(tokens)
    return tokens


def require_interface():
    assert (
        importlib.util.find_spec("docla.theme") is not None
        and load_theme is not None
        and ThemeError is not None
        and to_pt is not None
    ), "docla.theme.loader.load_theme, ThemeError and docla.theme.models.to_pt must exist"


def test_D1_to_pt_units():
    require_interface()
    assert abs(to_pt("20mm") - 56.693) < 0.001
    assert to_pt("1in") == 72
    assert to_pt("12pt") == 12
    assert to_pt(9.5) == 9.5
    assert abs(to_pt("2cm") - 56.693) < 0.001


def test_D1_to_pt_rejects_unknown_unit():
    require_interface()
    with pytest.raises(ValueError):
        to_pt("12px")


def test_D2_valid_theme_loads(tmp_path):
    require_interface()
    theme = load_theme(build_theme(tmp_path / "t"))
    assert theme.root == tmp_path / "t"
    assert theme.fonts_dir == tmp_path / "t" / "fonts"
    assert theme.info.name == "Test"
    assert theme.info.formats == ["slides", "doc"]
    assert theme.tokens.schema_ == 1
    assert theme.tokens.colour.roles == {
        "ink": "#1A1A1A",
        "paper": "#FFFFFF",
        "accent": "#0A5FD8",
    }
    assert theme.tokens.colour.contrast_min == 4.5
    assert theme.tokens.colour.usage["text"] == ["ink"]
    body = theme.tokens.type.scale["slides"].roles["body"]
    assert (body.family, body.size, body.weight, body.leading) == ("sans", 24, 400, 30)
    assert theme.tokens.type.scale["slides"].min_size == 18
    doc_body = theme.tokens.type.scale["doc"].roles["body"]
    assert (doc_body.weight, doc_body.leading) == (400, None)
    assert theme.tokens.spacing.unit == 4
    assert theme.tokens.spacing.scale == [4, 8, 16]


def test_D2_a4_page_and_margins_in_pt(tmp_path):
    require_interface()
    theme = load_theme(build_theme(tmp_path / "t"))
    doc = theme.tokens.pages["doc"]
    assert abs(doc.width - 595.276) < 0.01
    assert abs(doc.height - 841.89) < 0.01
    assert abs(doc.margin.top - 56.693) < 0.001
    assert doc.margin.right == 72
    assert doc.margin.bottom == 50
    assert doc.margin.left == 12
    assert (doc.columns, doc.gutter) == (1, 0)
    slides = theme.tokens.pages["slides"]
    assert (slides.width, slides.height) == (960, 540)


def test_D3_unknown_usage_role_is_refused(tmp_path):
    require_interface()
    load_theme(build_theme(tmp_path / "ok"))
    tokens = tokens_with(lambda t: t["colour"]["usage"].update(text=["ink", "nonesuch"]))
    with pytest.raises(ThemeError) as raised:
        load_theme(build_theme(tmp_path / "bad", tokens=tokens))
    assert "nonesuch" in str(raised.value)


def test_D3_unknown_family_is_refused(tmp_path):
    require_interface()
    load_theme(build_theme(tmp_path / "ok"))
    tokens = tokens_with(lambda t: t["type"]["scale"]["doc"]["body"].update(family="serifless"))
    with pytest.raises(ThemeError) as raised:
        load_theme(build_theme(tmp_path / "bad", tokens=tokens))
    assert "serifless" in str(raised.value)


def test_D4_missing_font_file_is_refused(tmp_path):
    require_interface()
    with pytest.raises(ThemeError) as raised:
        load_theme(build_theme(tmp_path / "bad", fonts=()))
    assert "Sans-Regular.ttf" in str(raised.value)


def test_D4_font_without_licence_record_is_refused(tmp_path):
    require_interface()
    other = "file: Other.ttf\nfamily: Other\nlicence: OFL-1.1\n"
    with pytest.raises(ThemeError) as raised:
        load_theme(build_theme(tmp_path / "bad", licences=other, fonts=("Sans-Regular.ttf", "Other.ttf")))
    message = str(raised.value)
    assert "Sans-Regular.ttf" in message
    assert "LICENSES.txt" in message


def test_D4_missing_licences_file_is_refused(tmp_path):
    require_interface()
    with pytest.raises(ThemeError) as raised:
        load_theme(build_theme(tmp_path / "bad", licences=None))
    message = str(raised.value)
    assert "Sans-Regular.ttf" in message or "LICENSES.txt" in message


def test_D5_format_without_pages_entry_is_refused(tmp_path):
    require_interface()
    tokens = tokens_with(lambda t: t["pages"].pop("doc"))
    with pytest.raises(ThemeError) as raised:
        load_theme(build_theme(tmp_path / "bad", tokens=tokens))
    assert "doc" in str(raised.value)


def test_D5_missing_tokens_file_is_refused(tmp_path):
    require_interface()
    with pytest.raises(ThemeError) as raised:
        load_theme(build_theme(tmp_path / "bad", tokens=False))
    assert "tokens.yaml" in str(raised.value)
