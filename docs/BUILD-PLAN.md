# docla: build plan and registration plan

Companion to `DESIGN.md` (the what and why). This file is the order of work. `DESIGN.md` section 18 holds the milestones
and their acceptance tests; this plan sequences them, breaks the first ones into tasks, and lists everything to register.
Status: 2026-11-03. The scope is everything in `DESIGN.md`, built in full: there are no deadlines, no spending cap and no
size estimates in this plan, only order and dependencies. Registration is largely done (section 7).

---

## 1. Principles for building this

1. **Spikes before structure.** Eight assumptions in the design are untested (DESIGN 18.1). Each spike is throw-away code with a written answer. Two of them (S1, S1b) decide how the whole layout and editor work, so they run first.
2. **Both formats from the first commit.** Every model carries `format: slides | doc`. M1 ships two slide and two doc components. No milestone after M5 is accepted on slides alone (DESIGN 18.0).
3. **Every rule ships with a seeded defect.** A rule without a fixture that fails it and a fixture that passes it is not merged.
4. **Look at the pages.** Every pull request that changes rendering attaches the rendered pages. A person has looked.
5. **Record Claude calls (cassettes) from day one.** Tests replay recorded responses; a small live eval runs nightly or on demand, never on every push.
6. **Vertical slices.** At each milestone the whole path works end to end on a thin case, rather than one layer being finished first.
7. **Never patch generated files; fix the source and rebuild.** LF line endings and a real installable package from the first commit.
8. **Build with Claude Code under a written brief.** The new repo gets an `AGENTS.md` (section 6 below) before any code, so agents working on it follow the same rules.

---

## 2. Phase 0: foundations (before any feature code)

Nothing here needs the spikes.

### 2.1 Registration

Done or prepared in 2026-11-03: see section 7 for the current state and what is left for you to run.

### 2.2 Licence files

* Copyright holder: Guillaume Picard (you). `LICENSE` (Apache-2.0, unmodified) and `NOTICE` are committed.
* Add `CONTRIBUTING.md` (DCO: `git commit -s`) and a DCO check in CI.
* Nothing from the private codebase is copied: new repository, fresh history, neutral theme and an OFL font only, and a CI grep gate for the old name and brand terms.

### 2.3 Repository bootstrap checklist

- [x] Repository created as `gwpicard/doclo`, renamed to `gwpicard/docla` and made public on 2026-11-03, first commit pushed: `LICENSE`, `NOTICE`, `README.md`, `pyproject.toml`, `package.json`, `src/docla/`, `.gitattributes`, `.gitignore`. Local clone: `~/PROJECTS/docla`.
- [ ] `main` protected, squash or rebase merges only, PRs required.
- [ ] `pyproject.toml` (package `docla`, Python version pinned, `uv` for environments and lock), `src/docla/` layout. Grep the tree for the earlier working names ("proof", "replo", "docklo", "doclo"); none may remain outside `docs/`.
- [ ] Tooling: ruff (lint and format), pyright or mypy, pytest, pre-commit.
- [ ] `.gitattributes` forcing LF; `.editorconfig`.
- [ ] CI (GitHub Actions, macOS and Linux): lint, types, unit tests, licence report of dependencies (fail on AGPL, e.g. PyMuPDF), DCO check, secret scan.
- [ ] Typst pinned by version; `docla doctor` stub that prints what is installed and what is missing.
- [ ] `AGENTS.md` and `CONTEXT.md` (the vocabulary from DESIGN section 3, one word per thing).
- [ ] `docs/` with `DESIGN.md` copied in as the starting point and `docs/decisions.md` for the decisions log.
- [ ] Issue templates and labels (area labels and severity labels) so defects are tracked from the start.
- [ ] `tests/fixtures/` skeleton: one slide fixture, one doc fixture, seeded-defect folders.
- [ ] Cassette recorder for the Claude wrapper (record on demand, replay by default).

Exit: a fresh clone installs with one command, CI is green on an empty package, and the licence files are in place.

---

## 3. Phase 1: spikes (answers, not code)

Order matters. Each spike has a kill or change criterion: what answer would change the design.

| Order | Spike | Why this position | If the answer is bad |
|---|---|---|---|
| 1 | **S1** slide section regions from Typst marks | Everything visual (overlays, micro loop crops, facts) rests on it | Fall back to title search plus pdfplumber text bounding boxes; the editor loses exact boxes |
| 2 | **S1b** same for a flowing two-column A4 page | Decides if documents can have exact regions; documents are a v1.0 commitment | Use the title-search fallback for documents only; fragment boxes are approximate and the flow rules use PDF facts alone |
| 3 | **S2** timings (swatch, 20 slides, 20 pages, 100 pages, extraction, rasterising) | Sets caching, preview latency and the real size limits (decision 16) | Add swatch caching and incremental compile earlier than planned |
| 4 | **S7** worktrees, separate git dir, merge driver | M7 depends on it; also decides decision 12 | Fall back to run-as-directory-copy plus the section merge in Python, without git |
| 5 | **S4** patch repair convergence | Proves the micro loop on seeded defects | Stronger deterministic fixes first; shrink what Claude is asked to do |
| 6 | **S3** critic reliability | Sets critic tier, image size, corroboration default | Raise critic to the larger model, or demote vision findings to advisory |
| 7 | **S6** Office fidelity | Shapes M9 scope; can be done later because M9 is late | State the limits in the UI; lean on the XML for numbers |
| 8 | **S5** brand-claim verification | Needs a real brand book; part of M9 | Add a human confirmation step for every extracted rule |
| 9 | **S8** document flow rules measurable | Needed for M6c | Reduce the document rule set to what can be measured; mark the rest advisory |

Run S1, S1b and S2 as one block (they share a Typst fixture). S3 and S4 call Claude and need recorded cassettes (section 5). Write each answer as a half-page note in `docs/spikes/` with numbers and the decision it fed.

Gate G1 (end of Phase 1): the design's assumptions are confirmed or amended, `DESIGN.md` is updated with the measured
timings and thresholds, and the open items in 21.2 are closed.

---

## 4. Phase 2 onward: milestones in order

The milestones and acceptance tests are in DESIGN 18.2. This section adds dependencies and the first tasks.

```
M1 skeleton ─► M2 theme ─► M3 writer/micro loop ─► M4 critic/macro loop ─► M5 visualiser MVP
                                                                              │
                         M6 documents (6a ► 6b ► 6c ► 6d) ◄───────────────────┘
                                                │
                         M7 run isolation ◄─────┤
                                                ▼
              M8 feedback and learning ─► M9 ingestion ─► M10 adaptation ─► M11 release
```

M9 can start its Office-reading work in parallel with M7/M8 because it does not depend on them until the calibration step.

| M | Depends on | Main risk | Gate |
|---|---|---|---|
| M1 | Phase 0, S1, S1b, S2 | Typst marks not exact | Round-trip property test; byte-identical PDFs |
| M2 | M1 | Component set too large to hand-build | Every chooser entry resolves; fixtures for each rule |
| M3 | M2, S4 | Repair does not converge | Heal eval: at least 90% cleared in 3 attempts, 99% facts kept |
| M4 | M3, S3 | Critic false positives cause thrash | "Slides complete" demo; critic precision gate |
| M5 | M4 | Overlays drift from PDF | Edit-to-render within 1 to 2 seconds |
| M6 | M5, S8 | Flow rules unmeasurable | Parity rows marked M6 green |
| M7 | M5, S7 | Merge edge cases | S7 scenarios in CI |
| M8 | M6, M7 | Learned rules overfit | Worked example on a deck and a report |
| M9 | M2 (start), M8 (finish) | Office fidelity | Synthetic brand book, PPTX and DOCX produce a theme |
| M10 | M8 | Drift | Repeat-mistake and first-shot rates improve; property test on strictness |
| M11 | all | Release polish | Fresh clone to demo deck and report; parity checklist green |

Gate G2 (after M4): the "slides complete" demo, which is the first end-to-end proof. Scope is unchanged: documents (M6)
and everything after it are built in full.

### 4.1 M1 task order (the first milestone, in detail)

1. Models: `Document`, `Section`, `Item`, `Patch`, `Finding`, `Rule` as Pydantic, with `format` on each; JSON Schema export in CI.
2. Working-file parser and serialiser with stable ids; property test: parse then serialise is the identity; edits keep ids.
3. Patch applier with `base_rev` and the guards (identity, schema validity first; ownership, fact and appearance guards as stubs that always pass, then filled in at M3).
4. Typst driver: compile with `--root`, `--font-path`, `--ignore-system-fonts`, `SOURCE_DATE_EPOCH=0`; assert byte-identical output twice.
5. Two slide components and two doc components in Typst with `section()` and `el()` marks and `fit-box`.
6. `read_marks` (`typst query`), then the facts extractor (pdfplumber) joined to the marks.
7. Six geometry and source rules (overflow, out-of-bounds, min font size, missing source, empty section, off-palette colour), each with passing and failing fixtures.
8. Swatch render of one section (slide and doc) plus the raster and crop helper.
9. CLI: `docla build`, `docla check`, `docla doctor`.
10. Acceptance run as in DESIGN 18.2, with screenshots attached.

---

## 5. Testing the Claude calls

* Tests replay recorded Claude responses (cassettes). Live evals run on demand and print their token use and cost per call from the first commit, so cost is visible, not capped.
* The scheduler, backoff, resumable builds and cost estimate (DESIGN 4.4) are built in M3.

---

## 6. Brief for the agents that will help build it (`AGENTS.md` in the new repo)

Seed content, to be written at Phase 0:

* Vocabulary from `CONTEXT.md`; one word per thing.
* Layout of the repo and the commands: build, check, test, eval, doctor.
* The seeded-defect rule, the look-at-the-pages rule, and the cassette rule.
* No agent attribution in commit messages or pull request bodies (if you want that convention; it is your private repo's habit, so decide whether it carries over).
* British or American English: choose one for docs and UI strings, and no em dashes if you keep that style.
* Never patch generated files; never commit fonts or assets without a recorded licence; never add a dependency without a licence check.
* Pull requests, not direct pushes to `main`; one job per PR; DCO sign-off on every commit.
* Old spellings still parse (applies once the first release ships): keep readers backward compatible.

---

## 7. Registration

Decisions (2026-11-03): personal GitHub account `gwpicard`; copyright holder Guillaume Picard; country Denmark;
legal work (trademark search and filing, lawyer opinions, employer paperwork) is out of scope for this plan; domain on hold.

### 7.1 State

| Place | Name | State |
|---|---|---|
| GitHub repository | `gwpicard/docla` | **Public.** Renamed from `gwpicard/doclo` on 2026-11-03; the old URL redirects. On GitHub the name `Docla` belongs to a user account, so the project lives under your account |
| Licence files | `LICENSE`, `NOTICE` | **Committed** (Apache-2.0, copyright 2026 Guillaume Picard) |
| PyPI | `docla` | **Not yet published.** Free when checked on 2026-11-03. The placeholder built earlier is named `doclo` (`dist/doclo-0.0.1.*`); rebuild it as `docla` before publishing. Needs your PyPI login |
| npm | `@gwpicard/docla` | **Not yet published.** Free when checked on 2026-11-03, as is the unscoped `docla`. npm refused the unscoped `doclo` as too similar to docx, docz, docco and doctoc and may refuse `docla` for the same reason (not tried), so the placeholder uses your scope. Needs only `npm publish` |
| Domain | | On hold. Not checked for `docla`; `doclo.com` and `doclo.ai` were already registered by others |

### 7.2 Commands for you to run

PyPI and npm both require your own login and two-factor code, which I cannot supply. Run these in the session with the `!` prefix.

PyPI (create the account and an API token at pypi.org first, scoped to "entire account" for the first upload):

```
! cd ~/PROJECTS/docla && uv publish --token <pypi-token>
```

npm (you are already logged in; the package is scoped, and `publishConfig` sets it public):

```
! cd ~/PROJECTS/docla && npm publish
```

After the first PyPI upload, replace the account-wide token: create a project-scoped token or, better, set up Trusted
Publishing for `gwpicard/docla` in the PyPI project settings so CI publishes without a stored secret. If you publish
nothing else, the names are still free until you do; whoever publishes first holds them.

### 7.3 Later, when relevant

* **Domain:** on hold. When you pick one, add the contact addresses (`security@`, `maintainers@`) for `SECURITY.md`.
* **Making the repository public:** `gh repo edit gwpicard/docla --visibility public --accept-visibility-change-consequences`. Do this when you are ready; nothing else depends on it.
* **Release time (M11):** replace the placeholders with the real release, add `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`.
* **Optional extras:** a Homebrew tap (`homebrew-docla`), a GHCR image, a Typst Universe package. None are required.

---

## 8. What happens next

1. You publish the PyPI and npm placeholders (7.2).
2. Finish Phase 0: the rest of the checklist in 2.3 (CI, tooling, `AGENTS.md`, `CONTEXT.md`, fixtures skeleton).
3. Phase 1: spikes in the order of section 3.
4. Gate G1: update `DESIGN.md` with measured numbers, then start M1.
