# Decisions log

The design's own log is `DESIGN.md` section 21.1. Decisions made while building go here, newest last.

| Date | Decision | Why |
|---|---|---|
| 2026-11-03 | `requires-python` is `>=3.12` | `DESIGN.md` section 0.4 names Python 3.12 |
| 2026-11-03 | Spikes S1 to S8 run by hand outside the loop; the loop builds after gate G1 | Spikes produce measured answers, not gate-checkable behaviour |
| 2026-11-03 | `DESIGN.md` and `BUILD-PLAN.md` live in `docs/`; pieces cite them by section number | Builders work in a fresh clone and cannot see the original folder |
| 2026-11-03 | Type checking uses mypy in strict mode, not pyright | The PyPI `pyright` wrapper downloads its engine from npm at run time, and unattended runs reach PyPI only |
| 2026-11-03 | The working-file parser is a hand-written line scanner, not markdown-it plugins | The brace attribute fence `::: {#id .section ...}` is not what the container plugin reads. This departs from the sentence in `DESIGN.md` section 5.5 |
| 2026-11-03 | `Document.format` is a required field, and the front matter `format` is stored there | `DESIGN.md` section 18.0 rule 1: every model carries `format` from the first commit |
| 2026-11-03 | ruff skips `tests/judge/` | Judge files are written by the judge writer and frozen at ready, so no builder may edit them, yet the repository-wide lint and format tests run over them |
| 2026-11-03 | No `.pre-commit-config.yaml` for now | Claude Code treats that file as sensitive and refuses to let a builder write it. A person adds it by hand later |
| 2026-11-03 | Work lands on the `loop/v0` branch and reaches `main` through one reviewed pull request | `Base merges: run` lets an unattended run build dependent pieces onto each other. The run never merges into `main` |
| 2026-11-03 | Documents use British English, no em dashes, and no agent attribution in commit messages or pull request bodies | Open items in `BUILD-PLAN.md` section 6, settled in `AGENTS.md` |
| 2026-11-03 | The DCO is checked at the pull request level: the description of a pull request carries one `Signed-off-by` line, commits need no trailer, and maintainers listed in `MAINTAINERS` are exempt | Everything reaches `main` through a pull request, and the commits made by the build loop cannot make the attestation. `CONTRIBUTING.md` keeps `git commit -s` as an optional convenience |
| 2026-11-03 | `main` requires a pull request, with no force pushes or deletions, and administrators can bypass it | Free branch protection became available when the repository went public. Status checks are advisory for now |
| 2026-11-03 | Typst is pinned at 0.15.1, and marks are read with `typst eval`, not `typst query` | Spikes S1, S1b and S2 (`docs/spikes/`). `query` is deprecated in 0.15.1, and PDFs are byte-identical across runs with `SOURCE_DATE_EPOCH=0` and `--ignore-system-fonts` |
| 2026-11-03 | Decision 12 stands: history in `.doclo/git` beside the user's repository, with the merge attribute in `.doclo/git/info/attributes` | Spike S7 (`docs/spikes/S7-worktrees.md`): 12 of 12 merge scenarios pass and the user's repository is never touched |
| 2026-11-03 | Overflow findings report per element (lines used, characters that free a line), and the fact guard is per field with a separate kept-facts check | Spike S4 (`docs/spikes/S4-repair.md`): 20 of 20 repairs converged with per-element findings against 16 of 20 without; facts kept 98.4% |
| 2026-11-03 | Widows, orphans and stranded headings are prevented in the theme (Typst default costs, sticky headings); near-empty pages and unbalanced columns are repaired by copyfit with N from the detector | Spike S8 (`docs/spikes/S8-flow-rules.md`): 12 of 12 seeded defects detected, 0 false positives on 14 controls |
