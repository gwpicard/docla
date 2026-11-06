import math

from docla.model.rules import Rule
from docla.model.source import Format
from docla.render.components import ComponentManifest
from docla.theme.models import Theme
from docla.theme.voice import Term, load_voice

HARD_PREFIX = "Hard rules that fail the build: "


def brief_card(
    theme: Theme,
    fmt: Format,
    intent: str,
    component: ComponentManifest,
    rules: list[Rule],
    max_tokens: int = 1500,
) -> str:
    """Return the compact theme summary for one section, trimmed to fit max_tokens."""
    voice = load_voice(theme)
    head = [
        f"BRIEF CARD theme={theme.info.name}@{theme.info.version} format={fmt} intent={intent} "
        f"component={component.name}",
        f"Capacity: {component.capacity_text()}",
    ]
    if fmt in voice.summary:
        head.append(f"Voice: {voice.summary[fmt]}")
    banned = f"Banned: {', '.join(sorted(voice.banned))}" if voice.banned else None
    preferred = _preferred_line(voice.terminology)
    entries = [f"{rule.title} (r:{rule.id})" for rule in _hard_rules(rules, fmt)]
    card = _assemble(head, banned, preferred, entries, keep=len(entries))
    for keep in range(len(entries) - 1, -1, -1):
        if _tokens(card) <= max_tokens:
            return card
        card = _assemble(head, banned, preferred, entries, keep)
    if _tokens(card) > max_tokens:
        card = _assemble(head, None, None, entries, keep=0)
    return card


def _preferred_line(terms: list[Term]) -> str | None:
    if not terms:
        return None
    entries = [f"{term.preferred} (not {', '.join(term.avoid)})" for term in sorted(terms, key=lambda t: t.preferred)]
    return "Preferred: " + "; ".join(entries)


def _hard_rules(rules: list[Rule], fmt: Format) -> list[Rule]:
    applies = [
        rule
        for rule in rules
        if rule.strength == "hard" and rule.status == "active" and rule.scope.format in (None, fmt)
    ]
    return sorted(applies, key=lambda rule: rule.id)


def _assemble(head: list[str], banned: str | None, preferred: str | None, entries: list[str], keep: int) -> str:
    lines = list(head)
    if banned is not None:
        lines.append(banned)
    if preferred is not None:
        lines.append(preferred)
    if not entries:
        lines.append(HARD_PREFIX + "none")
    elif keep > 0:
        lines.append(HARD_PREFIX + "; ".join(entries[:keep]))
    return "\n".join(lines)


def _tokens(text: str) -> int:
    return math.ceil(len(text) / 4)
