# Intent: CONTEXT.md at the repository root holds the project vocabulary, one word per thing.
import re
from pathlib import Path

CONTEXT = Path(__file__).resolve().parents[2] / "CONTEXT.md"

TERMS = [
    "Project", "Document", "Working file", "Section", "Intent", "Component", "Chooser", "Doctype",
    "Theme", "Token", "Rule", "Check", "Finding", "Fix", "Swatch", "Layout facts", "Look", "Critic",
    "Feedback", "Diagnosis", "Learning", "Probation", "Version",
]


def _text() -> str:
    assert CONTEXT.is_file(), "CONTEXT.md must exist at the repository root"
    return CONTEXT.read_text(encoding="utf-8")


def _body_rows() -> list[list[str]]:
    lines = [ln.strip() for ln in _text().splitlines() if ln.strip().startswith("|")]
    assert len(lines) >= 3, "CONTEXT.md must contain a table with a header, separator and rows"
    rows = []
    for ln in lines[1:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows


def test_D1_heading_and_one_word_per_thing():
    text = _text()
    first = next(ln for ln in text.splitlines() if ln.strip())
    assert re.match(r"# \S", first), "first line must be a level-one heading"
    assert "one word" in text.lower(), "must say there is one word per thing"


def test_D2_every_term_in_bold_in_a_table_row():
    rows = _body_rows()
    first_cells = [r[0] for r in rows]
    for term in TERMS:
        assert f"**{term}**" in first_cells, f"term {term!r} must appear as **{term}** in a table row"
    assert len(rows) == 23


def test_D3_every_row_has_a_meaning():
    rows = _body_rows()
    assert len(rows) == 23
    for row in rows:
        assert len(row) >= 2 and row[1].strip(), f"row {row[0]!r} needs a non-empty meaning"


def test_D4_no_term_defined_twice():
    rows = _body_rows()
    assert len(rows) == 23, "table must have exactly one row per term"
    names = [r[0].lower() for r in rows]
    assert len(names) == len(set(names)), "a term appears in more than one row"
