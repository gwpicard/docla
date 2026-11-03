# Intent: brief_card gives a deterministic, budgeted theme summary for one section whose rule lines name rule ids.
import re
import shutil
from pathlib import Path

try:
    from docla.theme import brief, neutral_theme
except ImportError as error:
    name = str(error.name)
    if name not in ("docla", "docla.theme", "docla.theme.brief") and not name.startswith("docla.theme."):
        raise
    brief = None
    neutral_theme = None

try:
    from docla.theme import load_theme
except ImportError as error:
    if str(error.name) not in ("docla", "docla.theme") and not str(error.name).startswith("docla.theme."):
        raise
    load_theme = None

try:
    from docla.theme import voice
except ImportError as error:
    if str(error.name) not in ("docla", "docla.theme") and not str(error.name).startswith("docla.theme."):
        raise
    voice = None

try:
    from docla.render.components import load_manifests
except ImportError as error:
    if str(error.name) not in ("docla", "docla.render", "docla.render.components"):
        raise
    load_manifests = None

from docla.checks.catalogue import m1_rules

SLIDE_IDS = [
    "geo.in-safe-area",
    "geo.min-font",
    "geo.palette",
    "geo.text-fits",
    "source.citations-resolve",
    "source.empty-section",
]
DOC_IDS = [i for i in SLIDE_IDS if i != "geo.text-fits"]


def _card(fmt="slides", intent="bullets", name="bullets", rules=None, theme=None, **kwargs):
    assert brief is not None and hasattr(brief, "brief_card"), "docla.theme.brief.brief_card must exist"
    assert neutral_theme is not None, "docla.theme.neutral_theme must exist"
    assert load_manifests is not None, "docla.render.components.load_manifests must exist"
    theme = theme if theme is not None else neutral_theme()
    component = load_manifests()[name]
    return brief.brief_card(theme, fmt, intent, component, m1_rules() if rules is None else rules, **kwargs)


def _hard_ids(card):
    line = next(line for line in card.split("\n") if line.startswith("Hard rules that fail the build:"))
    return re.findall(r"\(r:([^)]+)\)", line)


def test_D1_header_capacity_and_banned_lines():
    lines = _card().split("\n")
    assert lines[0] == "BRIEF CARD theme=neutral@0.1.0 format=slides intent=bullets component=bullets"
    assert lines[1] == "Capacity: items 1 to 6; item_chars 10 to 140; title_words 1 to 8"
    assert "Banned: journey, leverage, synergy, unlock" in lines


def test_D2_hard_rule_line_names_slide_rule_ids_sorted():
    assert _hard_ids(_card()) == SLIDE_IDS


def test_D2_doc_omits_slide_scoped_rule():
    card = _card("doc", "body", "body")
    assert _hard_ids(card) == DOC_IDS
    assert "geo.text-fits" not in card


def test_D3_same_inputs_and_reversed_rules_give_identical_strings():
    first = _card()
    assert first == _card()
    assert first == _card(rules=list(reversed(m1_rules())))
    assert len(first) > 0


def test_D4_small_budget_keeps_two_lines_and_drops_rules_first():
    full = _card()
    small = _card(max_tokens=60)
    assert small.split("\n")[:2] == full.split("\n")[:2]
    assert len(small) <= 240
    kept = re.findall(r"\(r:([^)]+)\)", small)
    assert kept == SLIDE_IDS[: len(kept)]
    assert len(kept) < len(SLIDE_IDS)
    if "Banned:" in small:
        assert "journey, leverage, synergy, unlock" in small


def test_D4_banned_line_dropped_only_after_every_rule_entry():
    small = _card(max_tokens=60)
    if "Banned:" not in small:
        assert "(r:" not in small


def _theme_without_voice(tmp_path: Path):
    assert load_theme is not None, "docla.theme.load_theme must exist"
    import docla

    source = Path(docla.__file__).parent / "themes" / "neutral"
    target = tmp_path / "neutral"
    shutil.copytree(source, target)
    shutil.rmtree(target / "voice")
    return load_theme(target)


def test_D5_theme_without_voice_file_has_no_voice_or_banned_line(tmp_path):
    theme = _theme_without_voice(tmp_path)
    card = _card(theme=theme)
    assert "Voice:" not in card
    assert "Banned:" not in card
    assert card.split("\n")[0].startswith("BRIEF CARD theme=neutral@0.1.0 format=slides")


def test_D5_load_voice_returns_empty_voice_when_file_absent(tmp_path):
    assert voice is not None and hasattr(voice, "load_voice"), "docla.theme.voice.load_voice must exist"
    empty = voice.load_voice(_theme_without_voice(tmp_path))
    assert empty == voice.Voice()
    assert empty.summary == {}
    assert empty.banned == []
