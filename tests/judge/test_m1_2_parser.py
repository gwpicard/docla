# Intent: parse() turns a working file into a Document plus findings and never raises.
try:
    from docla.source import parser
except ImportError as error:
    if error.name not in ("docla.source", "docla.source.parser"):
        raise
    parser = None

EXAMPLE = '''---
doctype: pitch-deck
format: slides                    # slides | doc
title: Asset integrity, readout
audience: the client's technical team, 8 people
purpose: leave them agreeing to a two-vessel pilot
theme: neutral                    # theme pack name or path
locale: en-GB
---

## Context

Free markdown. Never rendered. What the AI understood about the engagement:
who decides, what they fear, what was agreed. Read first on every resume.

## Sources

- [S1] workshop.vtt, 2026-08-28, transcript
- [S2] client-brief.pdf, "Integrity programme scope", March 2026

::: {#a7c31 .section intent="parallel-set" section="finding" icons="inspection,governance"}
## Three integrity concerns

- **Inspection intervals** were set in 2019 and never revised. [S1 00:41]
- **Data quality**: the pipeline drops 12% of readings. [S2 p.4]

> note: Ask the room which of the three they would fix first.
> spoken: The three concerns compound.
:::
'''

HEADER = "---\ndoctype: pitch-deck\nformat: slides\n---\n\n"
SOURCES = "## Sources\n\n- [S1] workshop.vtt, transcript\n\n"


def parse(text):
    assert parser is not None and hasattr(parser, "parse"), "docla.source.parser.parse must exist"
    return parser.parse(text)


def named(findings, name):
    return [f for f in findings if f.rule_id == "source." + name]


def one_section(fence_attrs, body, sources=SOURCES):
    text = HEADER + sources + "::: {" + fence_attrs + "}\n" + body + ":::\n"
    doc, findings = parse(text)
    assert len(doc.sections) == 1
    return doc.sections[0], doc, findings


def test_D1_example_document():
    doc, _ = parse(EXAMPLE)
    assert doc.format == "slides"
    assert doc.front == {
        "doctype": "pitch-deck",
        "title": "Asset integrity, readout",
        "audience": "the client's technical team, 8 people",
        "purpose": "leave them agreeing to a two-vessel pilot",
        "theme": "neutral",
        "locale": "en-GB",
    }
    assert doc.context.startswith("Free markdown. Never rendered.")
    assert doc.context.rstrip().endswith("Read first on every resume.")
    assert "[S1]" not in doc.context
    assert [(s.key, s.text) for s in doc.sources] == [
        ("S1", "workshop.vtt, 2026-08-28, transcript"),
        ("S2", 'client-brief.pdf, "Integrity programme scope", March 2026'),
    ]


def test_D2_example_section_and_no_findings():
    doc, findings = parse(EXAMPLE)
    assert findings == []
    assert len(doc.sections) == 1
    s = doc.sections[0]
    assert s.id == "a7c31"
    assert s.intent == "parallel-set"
    assert s.section == "finding"
    assert s.icons == ["inspection", "governance"]
    assert s.title == "Three integrity concerns"
    assert [i.head for i in s.items] == ["Inspection intervals", "Data quality"]
    assert [[(c.key, c.locator) for c in i.citations] for i in s.items] == [
        [("S1", "00:41")],
        [("S2", "p.4")],
    ]
    assert "[S1" not in s.items[0].body and "[S2" not in s.items[1].body
    assert "were set in 2019 and never revised." in s.items[0].body
    assert s.note == "Ask the room which of the three they would fix first."
    assert s.spoken == "The three concerns compound."


def test_D3_appearance_attribute_is_error_and_not_stored():
    s, doc, findings = one_section('#a1b2c .section intent="x" color=red', "## T\n")
    hits = named(findings, "appearance-in-source")
    assert len(hits) == 1
    f = hits[0]
    assert f.severity == "error"
    assert f.tier == "source"
    assert f.section_id == "a1b2c"
    assert f.remedy.class_ == "report"
    assert f.format == "slides"
    assert "color" not in s.extra_attrs
    assert "red" not in s.extra_attrs.values()


def test_D3_unknown_attribute_kept_with_one_warning():
    s, doc, findings = one_section('#a1b2c .section intent="x" mood=calm', "## T\n")
    assert s.extra_attrs == {"mood": "calm"}
    hits = named(findings, "unknown-attribute")
    assert len(hits) == 1
    assert hits[0].severity == "warning"
    assert hits[0].section_id == "a1b2c"
    import hashlib
    expected = hashlib.sha1(b"source.unknown-attribute|a1b2c|mood").hexdigest()
    assert hits[0].fingerprint == expected


def test_D3_quoted_value_with_spaces_kept():
    s, doc, findings = one_section('#a1b2c .section intent="x" mood="very calm"', "## T\n")
    assert s.extra_attrs == {"mood": "very calm"}


def test_D4_missing_id_warns_and_keeps_none():
    s, doc, findings = one_section('.section intent="x"', "## T\n")
    assert s.id is None
    hits = named(findings, "missing-id")
    assert len(hits) == 1
    assert hits[0].severity == "warning"


def test_D4_unknown_citation_warns():
    body = "## T\n\n- **A** known. [S1 p.2]\n- **B** unknown. [S9 p.1]\n"
    s, doc, findings = one_section('#a1b2c .section intent="x"', body)
    hits = named(findings, "unknown-citation")
    assert len(hits) == 1
    assert hits[0].severity == "warning"
    assert hits[0].section_id == "a1b2c"
    assert [c.key for c in s.items[1].citations] == ["S9"]
    assert [c.key for c in s.items[0].citations] == ["S1"]


def test_D5_empty_string_never_raises():
    doc, findings = parse("")
    assert doc is not None
    assert all(f.rule_id == "source.parse-error" for f in findings)


def test_D5_unterminated_fence():
    doc, findings = parse(HEADER + '::: {#a1b2c .section intent="x"}\n## T\n\n- **A** b\n')
    assert doc is not None
    errors = named(findings, "parse-error")
    assert errors and all(f.severity == "error" for f in errors)


def test_D5_invalid_front_matter():
    doc, findings = parse("---\n: : [unclosed\n  - {\n---\n\n## Context\n\nx\n")
    assert doc is not None
    assert named(findings, "parse-error")


def test_D5_arbitrary_text():
    doc, findings = parse("@@ ?? ::: ]]] \x00 not a working file\n}{\n")
    assert doc is not None
    assert named(findings, "parse-error")


def test_D6_data_block_code_block_and_gap():
    body = (
        "## Revenue\n\n"
        "```data\nlabel: Revenue\nvalues:\n  - 1\n  - 2\n```\n\n"
        '```python\nprint("hi")\n```\n\n'
        "[GAP: the year the second revision was signed off]\n"
    )
    s, doc, findings = one_section('#a1b2c .section intent="x"', body)
    assert s.data == {"label": "Revenue", "values": [1, 2]}
    assert len(s.code) == 1
    assert 'print("hi")' in s.code[0]
    assert "label: Revenue" not in s.code[0]
    assert s.paragraphs == ["[GAP: the year the second revision was signed off]"]
