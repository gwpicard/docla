"""Stable system prompt blocks shared by the M3 agents."""

from importlib.resources import files
from typing import Any

from docla.theme import Theme
from docla.theme.voice import load_voice

ROLES: tuple[str, ...] = ("gatherer", "planner", "writer.draft", "writer.repair")


def voice_block(theme: Theme) -> str:
    """Compile a deterministic voice block from the theme."""
    voice = load_voice(theme)
    lines = [f"VOICE theme={theme.info.name}@{theme.info.version}"]
    lines.extend(f"{format}: {summary}" for format, summary in sorted(voice.summary.items()))
    if voice.banned:
        lines.append(f"Banned: {', '.join(sorted(voice.banned))}")
    if voice.terminology:
        terms = sorted(voice.terminology, key=lambda term: term.preferred)
        entries = (f"{term.preferred} (not {', '.join(sorted(term.avoid))})" for term in terms)
        lines.append(f"Preferred: {'; '.join(entries)}")
    return "\n".join(lines)


def system_blocks(role: str, theme: Theme | None = None, brief: str | None = None) -> list[dict[str, Any]]:
    """Build the stable system blocks for one role."""
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role}")
    resources = files(__package__)
    texts = [resources.joinpath("header.txt").read_text(encoding="utf-8")]
    texts.append(resources.joinpath(f"{role}.txt").read_text(encoding="utf-8"))
    if theme is not None:
        texts.append(voice_block(theme))
    if brief is not None:
        texts.append(brief)
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text} for text in texts]
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks
