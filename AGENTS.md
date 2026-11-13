# docla

Claude-generated branded slides and documents (PDF) with a self-healing rulebook. Early development.

## Repository
Read `CONTEXT.md` for the vocabulary, and `docs/DESIGN.md` and `docs/BUILD-PLAN.md` for the design and the order of work.

Layout:
- `src/docla/`: the package
- `tests/`: the tests
- `tests/judge/`: frozen judges, never edit
- `tests/fixtures/`: test fixtures
- `scripts/`: helper scripts
- `docs/`: design and planning documents

Commands:
- `uv sync`: install dependencies
- `uv run python -m pytest`: run the tests
- `uv run ruff check .`: lint
- `uv run ruff format --check .`: check formatting
- `uv run mypy`: type-check
- `uv run docla doctor`: check the local setup

## Working rules
- Every rule ships with a seeded defect: a fixture that fails it and one that passes it.
- A change that affects rendering attaches the rendered pages.
- Claude calls in tests replay recorded cassettes. Make live calls only on demand.
- Never patch generated files. Fix the source and rebuild.
- Never commit fonts or assets without a recorded licence.
- Never add a dependency without a licence check.
- Open pull requests; do not push directly.
- One job per pull request.
- Sign off every commit under the DCO (`git commit -s`).
- Write British English.
- Use no em dashes.
- Put no agent attribution in commit messages or pull request bodies.

## The loop
This project uses AI Loop Kit. Pieces are GitHub issues with one `state:` label.
Only the gate (gate.py) changes a state label. The person merges every pull request into main.
Prepare command: `uv sync && (test ! -f web/package.json || (test -f web/package-lock.json && npm ci --prefix web) || npm install --prefix web)`
Test command: `uv run python -m pytest`
Agent: codex
Agent model: gpt-6.1-terra
Agent effort: medium
Standards: `STANDARDS.md`
Protected paths: `.claude/`, `.githooks/`, `.github/`, `LICENSE`, `NOTICE`
Idle limit: 10
Waiting limit: 6
Base branch: loop/v0
Base merges: run
Keep limit: 15
Sandbox domains: pypi.org, files.pythonhosted.org, registry.npmjs.org