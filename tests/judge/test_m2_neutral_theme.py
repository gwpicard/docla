# Intent: the shipped neutral theme loads with the agreed tokens, licensed fonts and readable contrast.
import re
import subprocess

try:
    import docla.theme as theme_pkg
except ImportError as error:
    if error.name != "docla.theme" and not str(error.name).startswith("docla.theme."):
        raise
    theme_pkg = None


def _theme():
    assert theme_pkg is not None and hasattr(theme_pkg, "neutral_theme"), "docla.theme.neutral_theme must exist"
    return theme_pkg.neutral_theme()


def _key(k):
    return getattr(k, "value", k)


def _by_key(mapping):
    return {_key(k): v for k, v in mapping.items()}


def _luminance(hex_colour):
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_D1_neutral_theme_loads_with_name_and_formats():
    theme = _theme()
    assert theme.info.name == "neutral"
    assert theme.info.version == "0.1.0"
    assert sorted(_key(f) for f in theme.info.formats) == ["doc", "slides"]


def test_D2_colour_roles_and_usage():
    colour = _theme().tokens.colour
    assert colour.roles == {
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
    assert colour.usage["text"] == ["ink", "ink-soft", "muted", "on-dark", "accent"]
    assert colour.usage["fill"] == ["surface", "surface-alt", "dark", "accent"]
    assert colour.usage["stroke"] == ["hairline", "ink-soft", "accent"]
    assert colour.contrast_min == 4.5
    assert colour.chart["sequence"] == ["#1A1A1A", "#4A4F55", "#8A9096", "#D5D8DB"]
    assert colour.chart["categorical"] == [
        "#2F5D8A",
        "#7A4DFF",
        "#00A37A",
        "#E0A100",
        "#C2410C",
        "#6B7280",
    ]


def test_D3_font_families_files_and_licence_records():
    theme = _theme()
    families = theme.tokens.type.families
    assert families["display"].name == "Source Serif 4"
    assert families["display"].files == ["SourceSerif4-Regular.ttf", "SourceSerif4-Semibold.ttf"]
    assert families["text"].name == "Inter"
    assert families["text"].files == ["Inter-Regular.ttf", "Inter-SemiBold.ttf"]
    licences = (theme.fonts_dir / "LICENSES.txt").read_text(encoding="utf-8")
    recorded = set(re.findall(r"^file:\s*(\S+)\s*$", licences, flags=re.MULTILINE))
    for family in families.values():
        for name in family.files:
            assert (theme.fonts_dir / name).is_file(), name
            assert name in recorded, name


def test_D4_pages_and_minimum_sizes():
    tokens = _theme().tokens
    pages = _by_key(tokens.pages)
    slides, doc = pages["slides"], pages["doc"]
    assert (slides.width, slides.height) == (960, 540)
    for side in ("top", "right", "bottom", "left"):
        assert getattr(slides.margin, side) == 40
        assert abs(getattr(doc.margin, side) - 56.693) <= 0.01
    assert abs(doc.width - 595.276) <= 0.01
    assert abs(doc.height - 841.89) <= 0.01
    assert doc.columns == 1
    scale = _by_key(tokens.type.scale)
    assert scale["slides"].min_size == 18
    assert scale["doc"].min_size == 9
    assert scale["slides"].roles["title"].size == 32
    assert scale["slides"].roles["body"].size == 20
    assert scale["doc"].roles["body"].size == 11
    assert scale["doc"].roles["h1"].weight == 600


def test_D5_text_colours_meet_contrast_minimum():
    colour = _theme().tokens.colour
    roles = colour.roles
    checked = []
    for name in colour.usage["text"]:
        background = roles["dark"] if name == "on-dark" else roles["surface"]
        ratio = _contrast(roles[name], background)
        assert ratio >= 4.5, f"{name} has contrast {ratio:.2f}"
        checked.append(name)
    assert checked == ["ink", "ink-soft", "muted", "on-dark", "accent"]


def test_D6_typst_lists_the_theme_fonts():
    theme = _theme()
    result = subprocess.run(
        ["typst", "fonts", "--ignore-system-fonts", "--font-path", str(theme.fonts_dir)],
        capture_output=True,
        text=True,
        check=True,
    )
    listed = result.stdout.splitlines()
    assert "Source Serif 4" in listed
    assert "Inter" in listed
