from typing import Any

import yaml  # type: ignore[import-untyped]

from doclo.model import Document, Item, Section

FRONT_FIRST = ["doctype", "format", "title", "audience", "purpose", "theme", "locale"]
ATTR_ORDER = [
    "intent",
    "section",
    "component",
    "because",
    "chart",
    "icons",
    "image",
    "span",
    "page",
    "owner",
    "lock",
    "redraft",
]


def _dump(value: Any) -> str:
    return str(yaml.safe_dump(value, sort_keys=False, width=10**6, allow_unicode=True))


def _front_matter(doc: Document) -> str:
    values = {**doc.front, "format": doc.format}
    rest = sorted(key for key in values if key not in FRONT_FIRST)
    keys = [key for key in FRONT_FIRST if key in values] + rest
    body = "".join(_dump({key: values[key]}) for key in keys)
    return f"---\n{body}---"


def _heading_blocks(doc: Document) -> list[str]:
    blocks = []
    if doc.context:
        blocks.append(f"## Context\n\n{doc.context}")
    if doc.sources:
        lines = "\n".join(f"- [{s.key}] {s.text}" for s in doc.sources)
        blocks.append(f"## Sources\n\n{lines}")
    return blocks


def _item(item: Item) -> str:
    text = item.body
    if item.head is not None:
        joiner = "" if text[:1] in (":", ",", ";", ".") else " "
        text = f"**{item.head}**{joiner}{text}".rstrip()
    for cite in item.citations:
        text += f" [{cite.key} {cite.locator}]" if cite.locator else f" [{cite.key}]"
    lines = ["- " + text] + [f"  - {sub}" for sub in item.sub]
    return "\n".join(lines)


def _attributes(section: Section) -> str:
    parts = ["#" + section.id] if section.id else []
    parts.append(".section")
    for name in ATTR_ORDER:
        value = getattr(section, name, None)
        if name == "icons":
            value = ",".join(section.icons) or None
        if value is not None:
            parts.append(f'{name}="{value}"')
    parts.extend(f'{name}="{section.extra_attrs[name]}"' for name in sorted(section.extra_attrs))
    return " ".join(parts)


def _quotes(section: Section) -> str:
    fields = [("note", section.note), ("spoken", section.spoken), ("source", section.source_line)]
    return "\n".join(f"> {name}: {value}" for name, value in fields if value is not None)


def _section_blocks(section: Section) -> list[str]:
    blocks = []
    if section.title is not None:
        blocks.append(f"## {section.title}")
    if section.items:
        blocks.append("\n".join(_item(item) for item in section.items))
    blocks.extend(section.paragraphs)
    blocks.append(_quotes(section))
    if section.data is not None:
        blocks.append(f"```data\n{_dump(section.data)}```")
    blocks.extend(f"```\n{code}\n```" for code in section.code)
    return [block for block in blocks if block]


def _section(section: Section) -> str:
    body = "\n\n".join(_section_blocks(section))
    middle = f"\n{body}" if body else ""
    return f"::: {{{_attributes(section)}}}{middle}\n:::"


def serialise(doc: Document) -> str:
    """Write a Document as canonical working-file text."""
    blocks = [_front_matter(doc), *_heading_blocks(doc), *(_section(s) for s in doc.sections)]
    return "\n\n".join(blocks) + "\n"
