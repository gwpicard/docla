import hashlib
import re
from typing import Any

import yaml  # type: ignore[import-untyped]

from docla.model import Citation, Document, Finding, Item, Remedy, Section, Source
from docla.model.source import Format

APPEARANCE = {"color", "font", "size", "x", "y"}
STRING_ATTRS = {"intent", "section", "component", "because", "redraft", "image"}
CHOICE_ATTRS = {
    "owner": {"human", "ai"},
    "lock": {"text", "all"},
    "page": {"new"},
    "span": {"column", "full"},
}
KNOWN_ATTRS = STRING_ATTRS | set(CHOICE_ATTRS) | {"icons"}
SEVERITY = {
    "parse-error": "error",
    "missing-id": "warning",
    "missing-intent": "error",
    "appearance-in-source": "error",
    "unknown-attribute": "warning",
    "unknown-citation": "warning",
    "invalid-format": "error",
}

FENCE_OPEN = re.compile(r"^:::\s*\{(.*)\}\s*$")
FENCE_CLOSE = re.compile(r"^:::\s*$")
CODE_FENCE = re.compile(r"^```\s*(\w*)\s*$")
ATTR = re.compile(r'#([^\s}]+)|\.([^\s}]+)|([A-Za-z_][\w-]*)=(?:"([^"]*)"|(\S+))')
CITATION = re.compile(r"\s*\[([A-Za-z]+\d+)(?:\s+([^\]]+))?\]")
HEAD = re.compile(r"^\*\*(.+?)\*\*(.*)$")
SOURCE_LINE = re.compile(r"^-\s*\[([^\]]+)\]\s*(.*)$")
QUOTE = re.compile(r"^>\s*(note|spoken|source):\s*(.*)$")
QUOTE_FIELDS = {"note": "note", "spoken": "spoken", "source": "source_line"}


class _Parser:
    def __init__(self) -> None:
        self.format: Format = "slides"
        self.findings: list[Finding] = []
        self.source_keys: set[str] = set()

    def report(self, name: str, message: str, detail: str, section_id: str | None = None) -> None:
        rule_id = f"source.{name}"
        digest = f"{rule_id}|{section_id or ''}|{detail}"
        fingerprint = hashlib.sha1(digest.encode()).hexdigest()
        self.findings.append(
            Finding(
                id=f"{rule_id}:{fingerprint[:10]}",
                rule_id=rule_id,
                tier="source",
                severity=SEVERITY[name],  # type: ignore[arg-type]
                format=self.format,
                section_id=section_id,
                message=message,
                fingerprint=fingerprint,
                remedy=Remedy.model_validate({"class": "report", "hint": message}),
            )
        )

    def front_matter(self, lines: list[str]) -> tuple[int, dict[str, Any]]:
        """Return the index of the first line after the front matter and its mapping."""
        if not lines or lines[0].strip() != "---":
            self.report("parse-error", "The file does not start with front matter.", "1")
            return 0, {}
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is None:
            self.report("parse-error", "The front matter is not closed with ---.", "1")
            return len(lines), {}
        try:
            loaded = yaml.safe_load("\n".join(lines[1:end]))
        except yaml.YAMLError as error:
            self.report("parse-error", f"The front matter is not valid YAML: {error}", "1")
            return end + 1, {}
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            self.report("parse-error", "The front matter is not a mapping.", "1")
            return end + 1, {}
        self.set_format(loaded.pop("format", None))
        return end + 1, loaded

    def set_format(self, value: object) -> None:
        if value in ("slides", "doc"):
            self.format = value
        else:
            self.report("invalid-format", "format must be slides or doc; slides is used.", "format")

    def attributes(self, raw: str, line_no: int) -> Section:
        section = Section(intent="")
        seen_intent = False
        warned: set[str] = set()
        for match in ATTR.finditer(raw):
            ident, _cls, name, quoted, bare = match.groups()
            if ident:
                section.id = ident
                continue
            if name is None:
                continue
            value = quoted if quoted is not None else bare
            if name == "intent":
                seen_intent = True
            self.assign(section, name, value, line_no, warned)
        if section.id is None:
            self.report("missing-id", "The section has no #id.", str(line_no))
        if not seen_intent:
            self.report("missing-intent", "The section has no intent.", "intent", section.id)
        return section

    def assign(self, section: Section, name: str, value: str, line_no: int, warned: set[str]) -> None:
        sid = section.id
        if name in APPEARANCE:
            self.report("appearance-in-source", f"{name} is appearance and does not belong in the source.", name, sid)
        elif name == "icons":
            section.icons = [part.strip() for part in value.split(",") if part.strip()]
        elif name in CHOICE_ATTRS:
            if value in CHOICE_ATTRS[name]:
                setattr(section, name, value)
            else:
                self.report("parse-error", f"{name}={value} is not a valid value.", str(line_no), sid)
        elif name in STRING_ATTRS:
            setattr(section, name, value)
        elif name not in warned:
            warned.add(name)
            section.extra_attrs[name] = value
            self.report("unknown-attribute", f"{name} is not a known attribute.", name, sid)
        else:
            section.extra_attrs[name] = value

    def sources(self, lines: list[str]) -> list[Source]:
        found = []
        for line in lines:
            match = SOURCE_LINE.match(line.strip())
            if match:
                found.append(Source(key=match.group(1), text=match.group(2).strip()))
        self.source_keys = {s.key for s in found}
        return found

    def item(self, text: str, section: Section) -> Item:
        citations = []
        for match in CITATION.finditer(text):
            key = match.group(1)
            citations.append(Citation(key=key, locator=match.group(2).strip() if match.group(2) else None))
            if key not in self.source_keys:
                self.report("unknown-citation", f"{key} is not in the sources.", key, section.id)
        text = CITATION.sub("", text).strip()
        head = None
        found = HEAD.match(text)
        if found:
            head, text = found.group(1), found.group(2).strip()
        return Item(head=head, body=text, citations=citations)

    def body(self, section: Section, lines: list[tuple[int, str]]) -> None:
        index = 0
        while index < len(lines):
            number, line = lines[index]
            index += 1
            fence = CODE_FENCE.match(line)
            if fence:
                index = self.code_block(section, lines, index, number, fence.group(1))
            else:
                self.body_line(section, line)

    def code_block(self, section: Section, lines: list[tuple[int, str]], index: int, start: int, tag: str) -> int:
        content: list[str] = []
        while index < len(lines):
            line = lines[index][1]
            index += 1
            closing = CODE_FENCE.match(line)
            if closing and not closing.group(1):
                text = "\n".join(content)
                if tag == "data":
                    self.data_block(section, text, start)
                else:
                    section.code.append(text)
                return index
            content.append(line)
        self.report("parse-error", "A code block is not closed.", str(start), section.id)
        return index

    def data_block(self, section: Section, text: str, line_no: int) -> None:
        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as error:
            self.report("parse-error", f"The data block is not valid YAML: {error}", str(line_no), section.id)
            return
        if isinstance(loaded, dict):
            section.data = loaded
        else:
            self.report("parse-error", "The data block is not a mapping.", str(line_no), section.id)

    def body_line(self, section: Section, line: str) -> None:
        stripped = line.strip()
        quote = QUOTE.match(stripped)
        if not stripped:
            return
        if quote:
            setattr(section, QUOTE_FIELDS[quote.group(1)], quote.group(2).strip())
        elif stripped.startswith("## ") and section.title is None:
            section.title = stripped[3:].strip()
        elif line.startswith("- "):
            section.items.append(self.item(line[2:], section))
        elif re.match(r"^\s+- ", line) and section.items:
            section.items[-1].sub.append(stripped[2:].strip())
        else:
            section.paragraphs.append(stripped)

    def document(self, lines: list[str], start: int) -> tuple[str, list[Source], list[Section]]:
        context: list[str] = []
        source_lines: list[str] = []
        pending: list[tuple[str, int, list[tuple[int, str]]]] = []
        target: list[str] | None = None
        index = start
        while index < len(lines):
            line = lines[index]
            fence = FENCE_OPEN.match(line)
            if fence:
                number = index + 1
                index, body = self.section_lines(lines, index)
                pending.append((fence.group(1), number, body))
                target = None
                continue
            index += 1
            heading = line.strip().lower()
            if heading == "## context":
                target = context
            elif heading == "## sources":
                target = source_lines
            elif target is not None:
                target.append(line)
        sources = self.sources(source_lines)
        sections = []
        for raw, number, body in pending:
            section = self.attributes(raw, number)
            self.body(section, body)
            sections.append(section)
        return "\n".join(context).strip(), sources, sections

    def section_lines(self, lines: list[str], index: int) -> tuple[int, list[tuple[int, str]]]:
        """Collect the body lines of the fence opened at index; return the next index."""
        start = index + 1
        body: list[tuple[int, str]] = []
        in_code = False
        index += 1
        while index < len(lines):
            line = lines[index]
            fence = CODE_FENCE.match(line)
            if fence:
                in_code = not in_code if fence.group(1) == "" else True
            if not in_code and FENCE_CLOSE.match(line):
                return index + 1, body
            body.append((index + 1, line))
            index += 1
        self.report("parse-error", "A section fence is not closed.", str(start))
        return index, body


def parse(text: str) -> tuple[Document, list[Finding]]:
    """Read a working file into a Document and findings. Never raises."""
    state = _Parser()
    try:
        lines = text.replace("\r\n", "\n").split("\n")
        start, front = state.front_matter(lines)
        context, sources, sections = state.document(lines, start)
        document = Document(front=front, format=state.format, context=context, sources=sources, sections=sections)
    except Exception as error:  # noqa: BLE001 - parse never raises
        state.report("parse-error", f"The file could not be read: {error}", "0")
        document = Document(front={}, format=state.format, sections=[])
    return document, state.findings
