# Spike S7: worktree runs, a separate git dir, and the section-aware merge driver

Date: 2026-11-03. git 2.49.0, macOS 15. Code: `docs/spikes/code/s7/`. Question (`DESIGN.md` 18.1): does a section-aware merge driver merge a
person's edit and an AI run correctly, on different and on the same sections, with docla's history in a separate git dir (`.docla/git`)
beside the user's own repository? Done when: 10 scripted merge scenarios pass.

## Set-up tested

Each scenario builds a fresh project folder that is **already the user's own git repository** (it tracks `README.md` and `deck.md`). docla then:

1. creates `.docla/` and runs `git --git-dir=.docla/git --work-tree=. init`;
2. adds `.docla/` to the user's `.git/info/exclude` and to `.docla/git/info/exclude`, so neither repository tracks it;
3. registers the merge driver in `.docla/git/config` and the attribute `*.md merge=docla-md` in `.docla/git/info/attributes`;
4. commits the base, creates a run with `git worktree add .docla/runs/r1 -b run/r1`, commits the AI change inside the run and the person's change on `main`, then merges `run/r1` into `main`.

The driver (`code/s7/merge_driver.py`) implements `DESIGN.md` 19.3 on the real `docla.source` parser and serialiser.

## Results: 12 of 12 scenarios pass

| # | Scenario | Driver | Plain text merge |
|---|---|---|---|
| 1 | Person and run edit different sections | pass | merges, same result |
| 2 | Same section, different fields | pass | merges, same result |
| 3 | Same text field: the person's text is kept and the run's text is recorded | pass | conflict markers |
| 4 | The run changes a non-text field (`span`) | pass | merges, same result |
| 5 | Both change a non-text field: the person's value stands | pass | conflict markers |
| 6 | The run inserts a section, the person edits another | pass | merges, same result |
| 7 | The person deletes a section the run edited: reported as a conflict, exit 1 | pass | conflict markers |
| 8 | Both reorder: the person's order wins | pass | conflict markers |
| 9 | The same change on both sides | pass | merges, same result |
| 10 | The run changes nothing | pass | merges, same result |
| 11 | Only the run reorders: the run's order is used | pass | conflict markers |
| 12 | The run deletes a section the person did not touch | pass | merges, same result |

Where the plain text merge succeeds it gives the same result as the policy, so the driver earns its place in exactly the five cases where a text merge stops (3, 5, 7, 8, 11).

Properties from 19.3, checked over all 12 scenarios: the driver is deterministic (same bytes twice), merging identical sides returns that side, and when either side made no change the result is the other side.

## Coexistence with the user's repository

Over all 24 test projects (12 with the driver, 12 without):

- the user's `HEAD` never moved, their branch list stayed `main`, and their `git worktree list` never showed a docla run;
- the user's `git status` never showed `.docla/`;
- plain `git` inside a run worktree resolves to `.docla/git` through the worktree's `.git` file;
- creating a worktree took 20 ms (median).

## Decisions

1. Keep decision 12: docla's history lives in `.docla/git`, beside any repository the user has. No fallback is needed.
2. Put `*.md merge=docla-md` in `.docla/git/info/attributes`, **not** in a tracked `.gitattributes` as 19.3 proposed. A tracked file belongs to the user's repository too.
3. docla always calls git with `--git-dir=.docla/git --work-tree=.` for `main`. At the project root plain `git` means the user's repository. Clear `GIT_DIR` and `GIT_WORK_TREE` from the environment before calling git.
4. Create `.docla/` before `git init`: `git --git-dir=.docla/git init` fails when the parent folder is missing.
5. The merge report (dropped run text, conflicts) must be written per run, for example `.docla/runs/<id>/dropped.json`. The spike writes one fixed file.

## Not covered

Two runs merged one after the other (19.5), a user repository that is itself a worktree or uses submodules, a user `.gitattributes` that sets attributes on `*.md` (git gives `info/attributes` the highest precedence, so docla's setting should win; not tested), the driver's start-up time per merge, Windows, and large binary assets.
