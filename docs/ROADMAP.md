# Roadmap: how the design splits into pieces

A piece is one GitHub issue: one change a builder can finish in about an hour, with three to six Contract items and a judge.
Counts below are estimates from `DESIGN.md` section 18 and are revised when a milestone is shaped. Milestone order and
dependencies are in `BUILD-PLAN.md` section 4. Shape a milestone only once what it depends on is merged and its spikes are
answered; the later milestones hang on spike results (S3, S4, S6 to S8).

## Wave 1: no Typst needed (shape now)

**Phase 0, foundations**

| Key | Piece | Depends on |
|---|---|---|
| P0.1 | Tooling: `requires-python >=3.12`, ruff lint and format, pyright, pytest config, pre-commit | none |
| P0.2 | CLI skeleton and `doclo doctor` (reports Python, Typst found or missing, pinned Typst version) | P0.1 |
| P0.3 | Hygiene: `.editorconfig`, LF check, grep gate for earlier working names | P0.1 |
| P0.4 | CI: GitHub Actions on macOS and Linux running lint, types and tests | P0.1 |
| P0.5 | `CONTRIBUTING.md` and a DCO check in CI | P0.4 |
| P0.6 | Dependency licence report that fails on AGPL | P0.4 |
| P0.7 | Secret scan in CI | P0.4 |
| P0.8 | `AGENTS.md` brief (`BUILD-PLAN.md` section 6) and `CONTEXT.md` (vocabulary from `DESIGN.md` section 2) | none |
| P0.9 | `tests/fixtures/` skeleton and a test that every rule has a passing and a failing fixture | P0.1 |
| P0.10 | Issue templates and area and severity labels | none |
| P0.11 | Cassette recorder: record on demand, replay by default, transport-agnostic | P0.1 |

**M1, the part that needs no Typst**

| Key | Piece | Depends on |
|---|---|---|
| M1.1 | Pydantic models (`Document`, `Section`, `Item`, `Patch`, `Finding`, `Rule`) with `format`; JSON Schema export checked in CI | P0.1 |
| M1.2 | Working-file parser with stable section ids | M1.1 |
| M1.3 | Working-file serialiser; property test: parse then serialise is the identity, edits keep ids | M1.2 |
| M1.4 | Patch applier with `base_rev`, identity and schema guards; ownership, fact and appearance guards as stubs | M1.3 |

## Wave 2: after gate G1 (spikes S1, S1b, S2 answered, Typst pinned)

| Key | Piece |
|---|---|
| M1.5 | Typst driver: pinned flags, `SOURCE_DATE_EPOCH=0`, byte-identical output |
| M1.6 | `marks.typ`, `theme.typ` stub and `page-setup` (`section()`, `el()`, `fit-box`) |
| M1.7 | Two slide components |
| M1.8 | Two doc components |
| M1.9 | `read_marks` via `typst query` |
| M1.10 | Facts extractor (pdfplumber) joined to marks, behind a `PdfFacts` interface |
| M1.11 | Rule engine: registry and finding emission |
| M1.12 | Source rules: missing source, empty section |
| M1.13 | Geometry rules: overflow, out-of-bounds, min font size |
| M1.14 | Off-palette colour rule |
| M1.15 | `Rasteriser` interface (pypdfium2) and crop helper |
| M1.16 | Swatch render for one section, both formats |
| M1.17 | `doclo build` and `doclo check` |

M1 acceptance (`DESIGN.md` 18.2) has a person look at the rendered pages. That is a manual step, not a piece.

## Later milestones (outline only)

| M | Scope | Pieces |
|---|---|---|
| M2 | Theme tokens, `theme.typ` generation, neutral theme and OFL font record, chooser, doctype loader, brief card, full slide component set, rule catalogue minus semantic | about 15 |
| M3 | Claude client and scheduler, gatherer, planner, writer draft and repair, fact guard, router, best-of-N, budgets, heal log, resumable builds, heal eval | about 12 |
| M4 | Contact sheets, pixel tier, critic with rubric and corroboration, macro loop, versions and manifest, ship gate | about 7 |
| M5 | FastAPI server and SSE, web scaffold, canvas overlays, outline, field editor, findings, live activity, heal replay, versions, file watcher | about 10 |
| M6 | 6a flow engine, 6b document components, 6c flow rules and repairs, 6d editor and doctypes | about 27 |
| M7 | Worktree runs, section-aware merge driver, run review screen, conflict policy | about 5 |
| M8 | Capture, diagnose, rule author, validation harness, impact preview, teach card, theme branch merge, probation, revert | about 11 |
| M9 | Ingestion for PDF, PPTX, DOCX, IDML, XLSX, images, fonts; safety checks; template mapping; comment import; calibration | about 18 |
| M10 | Signals, miners, FTS5 memory, autonomy dial, component and check authoring, dashboard | about 9 |
| M11 | Docs site, examples, evals in CI, installers, parity checklist | about 6 |

Roughly 150 pieces in all.

## Notes for shaping

- Wave 2 pieces that compile need a `typst` binary on the machine. Whether Typst is installed by Prepare (for example the PyPI `typst` package) or by hand decides whether those pieces can run walk-away; settle it at M1.5.
- Pieces that edit `.github/`, `AGENTS.md`, `LICENSE` or `NOTICE` name them under `Protected paths` and need `Settings: may change` where they touch CI.
- The web app (M5) adds `registry.npmjs.org` to `Sandbox domains` in `AGENTS.md`.
