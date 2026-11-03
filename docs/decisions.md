# Decisions log

The design's own log is `DESIGN.md` section 21.1. Decisions made while building go here, newest last.

| Date | Decision | Why |
|---|---|---|
| 2026-11-03 | `requires-python` is `>=3.12` | `DESIGN.md` section 0.4 names Python 3.12 |
| 2026-11-03 | Spikes S1 to S8 run by hand outside the loop; the loop builds after gate G1 | Spikes produce measured answers, not gate-checkable behaviour |
| 2026-11-03 | `DESIGN.md` and `BUILD-PLAN.md` live in `docs/`; pieces cite them by section number | Builders work in a fresh clone and cannot see the original folder |
