# Intent: serialise() writes a Document back to canonical working-file text so parse then serialise loses nothing.
import importlib.util
import re

try:
    import doclo.source as source
except ImportError as error:
    if error.name != "doclo.source" and not str(error.name).startswith("doclo.source."):
        raise
    source = None

try:
    import doclo.model as model
except ImportError as error:
    if error.name != "doclo.model" and not str(error.name).startswith("doclo.model."):
        raise
    model = None

EXAMPLE = '''---
doctype: pitch-deck
format: slides
title: Asset integrity, readout
audience: the client's technical team, 8 people
purpose: leave them agreeing to a two-vessel pilot
theme: neutral
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

THREE_SECTIONS = '''---
doctype: report
format: doc
title: Three parts
---

::: {#aaaaa .section intent="first"}
## One

Text one.
:::

::: {#bbbbb .section intent="second"}
## Two

Text two.
:::

::: {#ccccc .section intent="third"}
## Three

Text three.
:::
'''


def _need(owner, name):
    assert owner is not None and hasattr(owner, name), f"doclo.source.{name} must exist"
    return getattr(owner, name)


def serialise(doc):
    return _need(source, "serialise")(doc)


def parse(text):
    return _need(source, "parse")(text)


def _model(name):
    assert model is not None and hasattr(model, name), f"doclo.model.{name} must exist"
    return getattr(model, name)


def _fences(text):
    return re.findall(r"^::: \{.*?^:::$", text, flags=re.S | re.M)


def _rich_document():
    Document, Section, Item = _model("Document"), _model("Section"), _model("Item")
    Citation, Source = _model("Citation"), _model("Source")
    return Document(
        front={"doctype": "pitch-deck", "title": "Rich", "locale": "en-GB"},
        format="slides",
        context="Why this exists.",
        sources=[Source(key="S1", text="workshop.vtt, transcript")],
        sections=[
            Section(
                id="a1b2c",
                intent="compare",
                section="finding",
                component="two-column",
                because="two sides",
                owner="human",
                lock="text",
                page="new",
                span="full",
                redraft="shorter",
                image="hero.png",
                icons=["inspection", "governance"],
                title="Rich section",
                items=[
                    Item(
                        head="Lead",
                        body="first point.",
                        sub=["detail one", "detail two"],
                        citations=[Citation(key="S1", locator="00:41")],
                    ),
                    Item(body="plain point."),
                ],
                paragraphs=["A paragraph."],
                note="Say it slowly.",
                spoken="One sentence.",
                source_line="Source: survey",
                data={"rows": 3},
                code=["print(1)"],
                extra_attrs={"mood": "calm"},
            )
        ],
    )


def test_D1_example_round_trips_exactly():
    doc, _ = parse(EXAMPLE)
    assert serialise(doc) == EXAMPLE


def test_D1_front_matter_and_attribute_order_is_canonical():
    Document, Section = _model("Document"), _model("Section")
    doc = Document(
        front={"zeta": "z", "locale": "en-GB", "title": "T", "doctype": "d", "alpha": "a", "audience": "all"},
        format="doc",
        sections=[
            Section(
                id="a1b2c",
                intent="x",
                lock="all",
                span="column",
                section="s",
                owner="human",
                because="b",
                component="c",
                icons=["i1", "i2"],
                image="p.png",
                page="new",
                redraft="r",
            )
        ],
    )
    text = serialise(doc)
    assert text == (
        "---\n"
        "doctype: d\n"
        "format: doc\n"
        "title: T\n"
        "audience: all\n"
        "locale: en-GB\n"
        "alpha: a\n"
        "zeta: z\n"
        "---\n"
        "\n"
        '::: {#a1b2c .section intent="x" section="s" component="c" because="b" '
        'icons="i1,i2" image="p.png" span="column" page="new" owner="human" lock="all" redraft="r"}\n'
        ":::\n"
    )


def test_D1_body_order_is_title_items_paragraphs_notes_data_code():
    text = serialise(_rich_document())
    positions = [
        text.index("## Rich section"),
        text.index("- **Lead** first point. [S1 00:41]"),
        text.index("A paragraph."),
        text.index("> note: Say it slowly."),
        text.index("> spoken: One sentence."),
        text.index("> source: Source: survey"),
        text.index("```data"),
        text.index("print(1)"),
    ]
    assert positions == sorted(positions)
    assert "  - detail one" in text


def test_D2_generated_documents_round_trip_with_no_findings():
    assert importlib.util.find_spec("hypothesis") is not None, "hypothesis must be a dev dependency"
    from hypothesis import given, settings, strategies as st

    Document, Section, Item = _model("Document"), _model("Section"), _model("Item")
    Citation, Source = _model("Citation"), _model("Source")
    words = st.from_regex(r"[A-Za-z][A-Za-z0-9]{0,7}( [A-Za-z0-9]{1,7}){0,3}", fullmatch=True)
    attr_names = st.from_regex(r"[a-z]{4,8}", fullmatch=True).filter(
        lambda n: n not in {"intent", "section", "component", "because", "chart", "icons", "image", "span",
                            "page", "owner", "lock", "redraft", "color", "font", "size", "class", "title"}
    )

    @st.composite
    def documents(draw):
        count = draw(st.integers(0, 3))
        sources = [Source(key=f"S{n}", text=draw(words)) for n in range(1, count + 1)]
        keys = [s.key for s in sources]

        @st.composite
        def items(draw_inner):
            cites = []
            if keys:
                for key in draw_inner(st.lists(st.sampled_from(keys), max_size=2, unique=True)):
                    cites.append(Citation(key=key, locator=draw_inner(st.sampled_from([None, "00:41", "p.4"]))))
            return Item(
                head=draw_inner(st.one_of(st.none(), words)),
                body=draw_inner(words),
                sub=draw_inner(st.lists(words, max_size=2)),
                citations=cites,
            )

        @st.composite
        def sections(draw_inner):
            return Section(
                id=draw_inner(st.from_regex(r"[0-9a-f]{5}", fullmatch=True)),
                intent=draw_inner(words),
                section=draw_inner(st.one_of(st.none(), words)),
                owner=draw_inner(st.sampled_from([None, "human", "ai"])),
                lock=draw_inner(st.sampled_from([None, "text", "all"])),
                page=draw_inner(st.sampled_from([None, "new"])),
                span=draw_inner(st.sampled_from([None, "column", "full"])),
                title=draw_inner(st.one_of(st.none(), words)),
                items=draw_inner(st.lists(items(), max_size=3)),
                paragraphs=draw_inner(st.lists(words, max_size=2)),
                code=draw_inner(st.lists(words, max_size=2)),
                note=draw_inner(st.one_of(st.none(), words)),
                spoken=draw_inner(st.one_of(st.none(), words)),
                source_line=draw_inner(st.one_of(st.none(), words)),
                data=draw_inner(st.one_of(st.none(), st.dictionaries(st.from_regex(r"[a-z]{3,6}", fullmatch=True), st.integers(0, 99), min_size=1, max_size=3))),
                icons=draw_inner(st.lists(st.from_regex(r"[a-z]{3,8}", fullmatch=True), max_size=3, unique=True)),
                extra_attrs=draw_inner(st.dictionaries(attr_names, words, max_size=2)),
            )

        secs = draw(st.lists(sections(), max_size=3, unique_by=lambda s: s.id))
        return Document(
            front={"doctype": draw(words), "title": draw(words)},
            format=draw(st.sampled_from(["slides", "doc"])),
            context=draw(st.one_of(st.just(""), words)),
            sources=sources,
            sections=secs,
        )

    @settings(max_examples=60, deadline=None)
    @given(documents())
    def check(d):
        parsed, findings = parse(serialise(d))
        assert parsed == d
        assert [f for f in findings if f.severity == "error"] == []

    check()


def test_D2_example_parse_serialise_parse_is_equal_and_clean():
    original, _ = parse(EXAMPLE)
    again, findings = parse(serialise(original))
    assert again == original
    assert findings == []


def test_D2_rich_document_round_trips_with_no_error_findings():
    doc = _rich_document()
    parsed, findings = parse(serialise(doc))
    assert parsed == doc
    assert [f.rule_id for f in findings if f.severity == "error"] == []


def test_D3_serialise_is_stable_after_a_round_trip():
    doc = _rich_document()
    once = serialise(doc)
    assert serialise(parse(once)[0]) == once


def test_D3_messy_input_settles_to_canonical_text():
    messy = EXAMPLE.replace("\n\n::: {", "\n\n\n\n::: {").replace("## Sources\n\n", "## Sources\n\n\n")
    canonical = serialise(parse(messy)[0])
    assert canonical == EXAMPLE
    assert serialise(parse(canonical)[0]) == canonical


def test_D4_changing_one_title_keeps_ids_and_other_sections_text():
    doc, _ = parse(THREE_SECTIONS)
    before = serialise(doc)
    edited = doc.model_copy(deep=True)
    edited.sections[1].title = "Two, rewritten"
    after = serialise(edited)
    assert [s.id for s in parse(after)[0].sections] == ["aaaaa", "bbbbb", "ccccc"]
    fences_before, fences_after = _fences(before), _fences(after)
    assert len(fences_before) == len(fences_after) == 3
    assert fences_after[0] == fences_before[0]
    assert fences_after[2] == fences_before[2]
    assert "## Two, rewritten" in fences_after[1]
    assert fences_after[1] != fences_before[1]


def test_D5_output_is_lf_only_with_one_final_newline_and_one_blank_line_between_sections():
    doc, _ = parse(THREE_SECTIONS.replace("\n", "\r\n"))
    text = serialise(doc)
    assert "\r" not in text
    assert text.endswith(":::\n")
    assert not text.endswith("\n\n")
    assert "\n\n\n" not in text
    assert text.count("\n:::\n\n::: {") == 2


def test_D6_extra_attrs_follow_known_attributes_in_name_order_and_survive():
    Document, Section = _model("Document"), _model("Section")
    doc = Document(
        front={"doctype": "d"},
        format="slides",
        sections=[
            Section(
                id="a1b2c",
                intent="x",
                section="finding",
                extra_attrs={"zeta": "1", "alpha": "two words", "mid": "m"},
            )
        ],
    )
    text = serialise(doc)
    assert '::: {#a1b2c .section intent="x" section="finding" alpha="two words" mid="m" zeta="1"}\n' in text
    parsed, _ = parse(text)
    assert parsed.sections[0].extra_attrs == {"zeta": "1", "alpha": "two words", "mid": "m"}
    assert serialise(parsed) == text
