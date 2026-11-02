# doclo

Claude-generated branded slides and documents (PDF) with a self-healing rulebook. Early development.

## The loop
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
