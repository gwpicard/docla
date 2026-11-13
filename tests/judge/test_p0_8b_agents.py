# Intent: AGENTS.md gives agents the repository layout, commands and working rules while keeping the loop settings intact.
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[2] / "AGENTS.md"

LOOP_SECTION = """## The loop
This project uses AI Loop Kit. Pieces are GitHub issues with one `state:` label.
Only the gate (gate.py) changes a state label. The person merges every pull request into main.
Prepare command: `uv sync`
Test command: `uv run python -m pytest`
Agent: claude
Standards: `STANDARDS.md`
Protected paths: `.claude/`, `.githooks/`, `.github/`, `LICENSE`, `NOTICE`
Idle limit: 10
Waiting limit: 3
Base branch: main
Keep limit: 15
Sandbox domains: pypi.org, files.pythonhosted.org
"""


def _text() -> str:
    return AGENTS.read_text(encoding="utf-8")


def _section(heading: str) -> str | None:
    """Return the body of a `## heading` section, or None when it is absent."""
    lines = _text().splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if line.rstrip("\n") == f"## {heading}":
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "".join(lines[start:end])


def _has_all(text: str, needles: list[str]) -> list[str]:
    lowered = text.lower()
    return [n for n in needles if n.lower() not in lowered]


def test_D1_loop_section_unchanged():
    section = _section("The loop")
    assert section is not None, "AGENTS.md must keep a '## The loop' section"
    assert section.startswith("## The loop\n")
    # The settings may be tuned by the person; each setting key must stay present.
    keys = [line.split(":", 1)[0] for line in LOOP_SECTION.splitlines()[3:]]
    present = {line.split(":", 1)[0] for line in section.splitlines()}
    missing = [k for k in keys if k not in present]
    assert not missing, f"loop settings missing: {missing}"
    assert "Prepare command: `uv sync" in section
    assert "Test command: `uv run python -m pytest`" in section


def test_D1_title_lines_kept():
    text = _text()
    assert text.startswith("# docla\n\nClaude-generated branded slides and documents (PDF) with a self-healing rulebook. Early development.\n")


def test_D2_repository_section_names_docs_and_commands():
    section = _section("Repository")
    assert section is not None, "AGENTS.md must have a '## Repository' section"
    missing = _has_all(
        section,
        [
            "CONTEXT.md",
            "docs/DESIGN.md",
            "docs/BUILD-PLAN.md",
            "uv sync",
            "uv run python -m pytest",
            "uv run ruff check .",
            "uv run ruff format --check .",
            "uv run mypy",
            "uv run docla doctor",
        ],
    )
    assert missing == []


def test_D2_repository_section_lists_layout():
    section = _section("Repository")
    assert section is not None, "AGENTS.md must have a '## Repository' section"
    missing = _has_all(
        section,
        ["src/docla/", "tests/", "tests/judge/", "tests/fixtures/", "scripts/", "docs/"],
    )
    assert missing == []


def test_D3_working_rules_seeded_defect_pages_cassette():
    section = _section("Working rules")
    assert section is not None, "AGENTS.md must have a '## Working rules' section"
    missing = _has_all(section, ["seeded defect", "rendered pages", "cassette"])
    assert missing == []


def test_D4_working_rules_generated_licence_dependency_dco():
    section = _section("Working rules")
    assert section is not None, "AGENTS.md must have a '## Working rules' section"
    missing = _has_all(
        section,
        ["generated files", "fonts", "recorded licence", "licence check", "DCO", "git commit -s"],
    )
    assert missing == []


def test_D5_working_rules_language_and_attribution():
    section = _section("Working rules")
    assert section is not None, "AGENTS.md must have a '## Working rules' section"
    missing = _has_all(section, ["British English", "em dash", "attribution"])
    assert missing == []
