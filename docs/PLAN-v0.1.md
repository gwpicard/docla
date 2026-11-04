# docla v0.1 plan: B2 to M6, then the roadmap

Status: 2026-11-04. Written against `loop/v0` at 92a9462. Companion to `docs/DESIGN.md` (the what), `docs/BUILD-PLAN.md`
(the order) and `docs/ROADMAP.md` (piece counts). This file is the shaping source for an unattended AI Loop Kit 1.7.0 run:
a coordinator shapes every piece below into a GitHub issue from this text alone, so each row names its interfaces,
dependencies and acceptance. Where the design is silent or a frozen judge blocks the obvious route, section 8 gives the
default the coordinator uses until the owner says otherwise.

Contents: 1 Purpose and done. 2 What exists. 3 Global shaping rules. 4 Batches (B2, B3, M3, M4, M5, M6a to M6d).
5 Owner steps. 6 Run order and risks. 7 Later roadmap (M7 to M11) and nice to have. 8 Open questions with defaults.

---

## 1. Purpose and definition of done for v0.1

**v0.1, the first good working version, is everything through M6: decks and reports.** It ends where DESIGN 18.2's M6 row
ends. M7 to M11 follow (section 7).

v0.1 is done when all of these hold:

| # | Requirement | Source |
|---|---|---|
| 1 | M2 accepted: every chooser entry resolves; each rule has a failing and a passing fixture; brief card deterministic (done in B1) | DESIGN 18.2 M2 |
| 2 | M3 accepted: heal eval clears at least 90% of seeded sections in at most 3 attempts with at least 99% of facts kept | 18.2 M3, 16.4 |
| 3 | M4 accepted: a deck with seeded flow problems repaired in at most 2 rounds; the ship gate refuses until clean; critic precision gate met; the "slides complete" demo (gate G2) | 18.2 M4, BUILD-PLAN 4 |
| 4 | M5 accepted: edit a bullet and see the new render and finding in about 1 to 2 s; an external edit of the `.md` appears | 18.2 M5 |
| 5 | M6 accepted: the parity rows marked M6 are green, and the M6d acceptance report builds | 18.2 M6, 18.3, 18.4 |
| 6 | Definition of done for each milestone: tests incl. seeded defects pass; docs updated; a person has looked at the rendered pages (attached to the PR); no unexplained cost rise in the end-to-end eval; both formats covered where marked | 18.5 |

Parity rows (DESIGN 18.4) that v0.1 must turn green, slides and docs:

| Capability | Slides | Docs | Built in |
|---|---|---|---|
| Working file, patches, ownership | done | done | M1 |
| Tokens, theme, brief card | done | done | M2 (B1) |
| Component library with capacity and swatch | B2 | M6b | M2 / M6b |
| Micro loop (draft, sense, repair, best-of-N) | M3 | M6c | M3 / M6c |
| Vision critic and macro loop | M4 | M6c | M4 / M6c |
| Ship gate and versions | M4 | M4 | M4 |
| Visualiser: click, edit, findings, replay | M5 | M6d | M5 / M6d |
| Flow rules (fill, balance, orphans, floats) | n/a | M6c | M6c |

M6d acceptance (DESIGN 18.3): a 12-page two-column report with 6 charts, 2 long tables and footnotes builds; regions
overlay correctly; a seeded near-empty last page is repaired by copyfit; a human edit to one paragraph re-renders within
the fast-preview target; the report passes the same ship gate as a deck.

Paid or manual acceptance steps (heal eval, critic precision eval, looking at pages) are owner steps (section 5). The
loop builds the code and the offline tests for them; the owner runs them.

---

## 2. What exists now (verified in code, 2026-11-04)

| Module | What is there | Key interfaces |
|---|---|---|
| `docla.model` | `Document`, `Section`, `Item`, `Source`, `Citation`, `Patch`, `PatchOp`, `Rule`, `Finding`, `Box`, `Remedy`, `Provenance`, `Scope(format, roles)`; JSON Schema export (`docla.model.schema.export_schemas`, checked by `tests/test_schemas_current.py` against `docs/schemas/`) | `Format = Literal["slides","doc"]`; `Rule` rejects hard+measured |
| `docla.source` | line-scanner parser `parse(text) -> (Document, findings)`, canonical `serialise`, `IdStore`/`stamp`, `apply_patch(doc, patch, fact_guard)` with guards, `apply_to_file` with oplog | `FactGuard = Callable[[Document, Section], bool]`; `TEXT_FIELDS`; `PatchRejected(code, message)`; parser findings `source.parse-error`, `missing-id`, `missing-intent`, `appearance-in-source`, `unknown-attribute`, `unknown-citation`, `invalid-format` |
| `docla.render.typst` | pinned Typst 0.15.1 driver | `compile_pdf(main, root, out, font_paths)`, `run_typst`, `TypstError` family |
| `docla.render.kit` | packaged `lib/` (marks.typ, stub theme.typ) and `components/` | `lib_dir()`, `components_dir()`, `read_tokens(root)` |
| `render/lib/marks.typ` | `section(id, body)`, `el(role, id, body, width:)`, `el-full-width`, `fit-box(role, id, w, h, body)` (clip false), one label `<docla-mark>` | marks told apart by `kind` |
| `render/lib/theme.typ` (stub) | tokens `{ink, paper, accent, muted}`, `colour(name)`, `page-setup(format, body)` | frozen judges render M1 components with it |
| `docla.render.marks` | `read_marks` via `typst eval` | `SectionMark`, `ElementMark`, `FitMark` |
| `docla.render.components` | 4 manifests (`statement`, `bullets` slides; `body`, `callout` doc) | `ComponentManifest(name, format, label, intents, capacity, elements)`, `load_manifests(folder=None)`, `capacity_text()`, `ManifestError` |
| `docla.render.chooser` + `chooser.yaml` | intents `statement`, `bullets` (slides), `body`, `callout` (doc); `when` keys `count`, `max_item_chars`, `has_data`, `has_image`, `is_first`, `is_last` | `load_chooser(path=None, manifests=None)`, `Chooser.choose(section, fmt, index, total)`, `.knows`, `.names`, `ChooserError` |
| `docla.render.compose` | `compose(doc, chooser=None) -> Composition`, `assemble(comp, dest, *, theme=None) -> main.typ`, `component_for`, `font_paths`, `M1_COMPONENTS` | `ComposedSection(id, component, props)`; props keys exactly `id, title, items, paragraphs, source_line`; item props exactly `head, body, cites` (keys only) |
| `docla.render.swatch` | one section alone on its format page | `swatch(doc, section_id, workdir, theme=None) -> SwatchRender(pdf, main, facts, pngs)` |
| `docla.facts` | `PdfPlumberFacts` (words, shapes, colours), `join`, `layout_facts(pdf, main, root, extractor, font_paths)`, `PdfiumRasteriser`, `crop` | `LayoutFacts(pdf_sha256, pages, words, shapes, marks)`, `PlacedWord.role/section_id`, `Rasteriser`, `PdfFacts` protocols. No images in facts yet |
| `docla.checks` | engine with tier order and per-section blocking on errors; checks registered by kind: `citations-resolve`, `empty-section`, `intent-known`, `fits`, `in-safe-area`, `font-size`, `colour-in-set` | `CheckContext(doc, facts, tokens, theme)`, `register(kind)`, `make_finding(...)`, `run_checks(rules, ctx)`, `fingerprint`; `catalogue.m1_rules()` (6 ids), `catalogue.all_rules()` = m1 + `source.M2_RULES` (`source.intent-known`) |
| `docla.theme` | `load_theme(root)`, `neutral_theme()`, `Theme(root, info, tokens)`, `to_pt`, `ThemeError`, `render_theme_typ(theme)` (exports `tokens`, `chart`, `text-font`, `type-scale`, `space-unit`, `space-scale`, `pages`, `colour()`, `type-style(format, role)`, `space(n)`, `page-setup(format, body)`; slides page margin 0, doc keeps margins), `brief_card(theme, fmt, intent, component, rules, max_tokens)`, `load_voice(theme) -> Voice(summary, banned)` | `Tokens(schema, colour, type, pages, spacing)` |
| `themes/neutral` | Source Serif 4 + Inter (OFL, `fonts/LICENSES.txt`), 9 colour roles, slides 960x540 margins 40, doc A4 margins 20 mm, 1 column; slides min 18 (caption 14), doc min 9; `voice/terminology.yaml` (summary, banned) | packaged in `src/docla/themes/neutral/` |
| `docla.doctypes` | `load_doctype(path, chooser)`, `load_doctypes()` -> `pitch-deck`, `report` | `Doctype`, `OutlineEntry(section, intent, required, repeat, fill, from, children)`, `RuleRef`, `Question`, `DoctypeError` |
| `docla.agents.cassette` | record/replay keyed by sha256 of the request dict; `DOCLA_RECORD=1` records | `Cassette(path, mode, transport)`, `Cassette.from_env`, `Transport = Callable[[dict], dict]`, `CassetteMiss` |
| `docla.cli` | `docla doctor`, `docla build FILE [--out] [--theme]`, `docla check FILE [--out] [--theme]` (writes `<stem>.findings.json`; runs `all_rules()`; when compose fails runs the source tier only) | exit 0 clean, 1 errors, 2 build failure |
| Not yet | no anthropic client, no loop, no store, no server, no web app, no image facts, no pixel checks, no DSL selectors, no theme rule files | |

Frozen behaviour the plan must not contradict (from `tests/judge/`):

| Pin | Judge | Consequence for later pieces |
|---|---|---|
| `load_manifests()` returns exactly `body, bullets, callout, statement` with pinned capacities and elements | test_m2_manifests D1 | New components go in a second folder (B2.02), never in `render/components/` |
| `load_doctypes()` returns exactly `pitch-deck`, `report`; their outlines pinned | test_m2_doctypes D1 | New and richer doctypes live in the theme (`themes/neutral/doctypes/`, M6d.01) |
| props keys exactly `id, title, items, paragraphs, source_line`; item props `head, body, cites` | test_m1_compose D1 | New section data travels in a new `ComposedSection.content` (B2.04) |
| intent `timeline` has no slides component; a slides doctype naming `timeline` fails to load; `body` is not a slides intent; `statement` is not a doc intent | test_m1_compose D2, test_m2_intent_known, test_m2_doctypes D2 | The timeline intent is `chronology` (section 8, Q1). Never add slides entries for `body` or `timeline`, or doc entries for `statement` |
| packaged chooser: statement section -> `statement`; bullets with 3 items -> `bullets`; body -> `body`; callout -> `callout` | test_m2_chooser D1 | `when` clauses may not capture these cases |
| `M1_COMPONENTS` pinned; `m1_rules()` 6 ids in order; `source.RULES` exactly 2 rules | test_m1_compose, test_m1_17 D6, test_m1_12 | New rules go in new lists appended to `all_rules()` |
| stub `theme.typ` tokens `{ink, paper, accent, muted}` | test_m1_14 | Stub unchanged; new components need the theme (B2 rule) |
| statement title fit-box `have` 300; bullets title then body fit-boxes, items at x 40, y 120 to 500; overflow stays one page; `fit-box` emits one fit mark, wrap element height equals the box height | test_m1_7, test_m1_6 D4 | Overflow display (B2.06) must not add marks or change sizes |
| neutral tokens: colour roles, slides margins 40, doc margins 20 mm, `doc.columns == 1`, slides min 18, title 32, body 20, doc body 11 | test_m2_neutral_theme | Two-column reports use a per-document override (M6a.01); caption size is free to change |
| With a theme copy whose slides margins are 120 pt, `check` flags `geo.in-safe-area` on a clean bullets slide | test_m2_theme_in_builds D3 | Slide components keep fixed frames; they do not read margins from the theme |
| `docla check` on the clean SLIDES/DOC texts prints exactly `no findings` (m1_17 D3/D4, theme_in_builds D2); the text-fits fail fixture reports `error geo.text-fits`; pass fixtures exit 0 | test_m1_17, test_m2_theme_in_builds | Every rule added to `all_rules()` must be silent on those texts at every severity, and must not raise an error that blocks `geo.text-fits` on its fail fixture (see B3 notes) |
| `tests/test_hygiene.py`: no CR bytes; the words replo, docklo, doclo, proof are banned in tracked files outside `docs/` | test_hygiene | Never write the standalone word "proof" in code, tests, fixtures or lockfiles |

The clean texts a new `all_rules()` rule must stay silent on (quote them in B3 judges): m1_17 `SLIDES` (statement "One pilot
is enough"; bullets "Why it works" with "Short intervals catch drift early. [S1 00:41]" and "Cheap to repeat."), m1_17 `DOC`
(body "Findings", one cited paragraph), theme_in_builds `SLIDES` (three short cited items), `DOC` (body plus a callout
with one paragraph and no items), `BULLETS_ONLY`.

---

## 3. Global rules for shaping from this plan

Spec shape (as in issues #97 to #105): Intent, Out of scope, Approach, Contract (D1 to Dn), Exit (judge command and file),
Risks (`Protected paths`, `New dependency`, `Shared files`, `Needs services`, `Open choices`, `Depends on`).

1. **One job per piece**, about an hour of building, 3 to 6 Contract items, its own judge file
   `tests/judge/test_<key>_<slug>.py` (key lower case, dots as underscores, e.g. `test_b2_08_cover.py`). Judges are frozen
   once the piece is ready; never edit an existing judge.
2. **Approach names interfaces**: the existing functions, classes and files a piece calls or changes (section 2 and the
   "Builds on" column), with module paths. New public names are stated exactly as in this plan.
3. **Depends on** lists piece keys from this plan; the coordinator maps them to issue numbers when it creates issues.
4. **Judges assert before use**: a judge first asserts that each module, function, file or fixture it uses exists, with a
   message naming it (the `_optional` / `_require_interface` pattern in current judges), so a missing piece fails cleanly.
5. **Already-true items are marked `(stays)`** in the Contract, so the judge pins them without asking for new work.
6. **Never change frozen judges' pinned behaviour** (section 2 table). Extend through new lists, functions and folders,
   as `source.M2_RULES` and `catalogue.all_rules()` did. A piece whose obvious route breaks a frozen judge must take the
   route this plan names, or stop with an `Open choices` entry.
7. **Every rule ships a seeded defect pair**: `tests/fixtures/seeded-defects/<rule-id>/fail/` and `/pass/`, each holding a
   `doc.md` (or `main.typ`, or the files the rule needs, such as `before.md`/`after.md`). The judge shows the fail side
   produces the rule's finding and the pass side does not.
8. **Rule ids** use the code's prefixes: `source.` (DESIGN `src.`), `geo.`, `pix.`, `sem.`, plus `deck.` for deck-pace
   doctype rules (DESIGN 8.4).
9. **No Anthropic API calls in builds or tests.** Claude calls go through a `Transport` (`docla.agents.cassette.Transport`);
   tests use fake transports or replay cassettes. A piece never records a cassette. Code that needs a recorded cassette
   ships its test with a fake and leaves the cassette test to an owner step (section 5).
10. **Network**: builders reach pypi.org and files.pythonhosted.org only. No npm until the owner merges the
    `registry.npmjs.org` change to `AGENTS.md` (owner step O9).
11. **New dependencies** are named in the spec's `New dependency:` line with licence, and must pass
    `scripts/licence_report.py` (no AGPL). Planned: `anthropic` (MIT, M3.01), `fastapi` (MIT), `uvicorn` (BSD-3),
    `httpx` (BSD-3, test client; already pulled by anthropic) in M5.01. SSE uses FastAPI's plain `StreamingResponse`
    (DESIGN C.6), not `sse-starlette`. File watching uses a stdlib polling loop, not `watchfiles`. `ruamel.yaml` (MIT) is
    not needed before M8. npm (after O9): `vite`, `react`, `react-dom`, `@tanstack/react-query`, `vitest`,
    `@testing-library/react`, `jsdom` (all MIT), `typescript` (Apache-2.0).
12. **Protected paths** (`.claude/`, `.githooks/`, `.github/`, `LICENSE`, `NOTICE`, and `AGENTS.md` by practice) are
    touched only by the pieces flagged "owner merge" below. None is in an overnight batch.
13. **Model changes** (`docla.model`) regenerate `docs/schemas/*.schema.json` with `docla.model.schema` in the same piece
    (fix the source, rebuild the generated file; never hand-edit it).
14. **Rendering pieces attach rendered pages** to the PR (AGENTS.md); the judge cannot check this, the owner looks.
15. **Components added after M1** live in `src/docla/render/library/` (B2.02), use only `colour()` roles of the theme,
    `type-style(format, role)` and `space(n)` from the generated `theme.typ`, place slide frames with
    `lib/frames.typ` (B2.01), never contain colour literals (`rgb(`, `luma(`, `cmyk(`, `#RRGGBB`), wrap the section in
    `section()`, every drawn element in `el()` and every fixed slide frame in `fit-box()`, and are tested with
    `neutral_theme()` (rendering them with the stub theme is unsupported).
16. **Shared files** that many pieces edit (`render/chooser.yaml`, `checks/catalogue.py`, `cli.py`,
    `render/compose.py`) are listed in each spec's `Shared files:` line; pieces in a chain that edit the same file depend
    on the previous one so `Base merges: run` stacks them.
17. Writing: British English, no em dashes, no agent attribution, vocabulary from `CONTEXT.md`.

---

## 4. Batches in build order

Columns: **Key**, **Piece**, **Scope** (one line), **Builds on** (existing or earlier-piece interfaces), **Dep** (Depends
on), **New dep**, **Fixtures and acceptance**. "fx" = seeded-defect pair.

### B2. M2 full slide component set, plus the overflow and citation follow-ups (26 pieces)

Goal: DESIGN 8.2 slides list (cover, agenda, chapter-break, statement, bullets (cards), two-column, comparison,
key-figures, quote, image-with-text, full-image, chart, table, timeline, process, matrix, people, contact, closing),
each with manifest, chooser entry, fixture, capacity and golden layout facts. Statement and bullets exist.

Component conventions for every component piece (B2.08 to B2.25):
- Files `src/docla/render/library/<name>.typ` and `<name>.yaml`; manifest fields as `ComponentManifest` plus `fixture`
  (path of `tests/fixtures/components/<name>.yaml`, a Section as YAML filled to the manifest's typical capacity).
- Chooser entry appended under its intent in `src/docla/render/chooser.yaml`; the intent's `describes` is one plain line.
- Frames: title in `title-frame`, content in `content-frame` (B2.01); every fixed frame is a `fit-box` so `geo.text-fits`
  works; item-like elements use role `item` so the per-item overflow detail of `geo.text-fits` applies.
- Judge contract template: (D1) manifest loads through `all_manifests()` with the stated format, intents, capacity,
  elements, label; (D2) the chooser routes the stated sections to it and the pinned M1 routes still hold (stays);
  (D3) its fixture renders with `neutral_theme()` to one 960x540 page with section and element marks for each role;
  (D4) at the capacity maximum every fit mark is ok and at maximum plus one some fit mark is not; (D5) `docla check` of a
  deck built from the fixture reports no findings; (D6) no colour literals in the `.typ`.
- Acceptance: the PR attaches the fixture's rendered page and the max-plus-one overflow page.

| Key | Piece | Scope | Builds on | Dep | New dep | Fixtures and acceptance |
|---|---|---|---|---|---|---|
| B2.01 | Slide frames and caption size | Add `render/lib/frames.typ` with `title-frame` (40, 40, 880 x 60 pt), `content-frame` (40, 120, 880 x 380 pt), `full-frame` (40, 40, 880 x 460 pt) and `slide-title(sec)` that draws the title in a `fit-box("title", ...)` with `type-style("slides","title")`; raise neutral slides `caption` to 18 pt and add slides role `figure` (display, 48, weight 600) and `label` (text, 18) to `tokens.yaml` | `kit.lib_dir()`, `render_theme_typ`, neutral `tokens.yaml` | none | none | Judge: frames compile under the generated theme and report the stated boxes; every neutral slides role is at least `min_size`; stub `theme.typ` tokens unchanged (stays); bullets and statement frames unchanged (stays). Frames are fixed, not read from the theme's margins (section 8, Q9) |
| B2.02 | Component library folder | `docla.render.components.library_dir()` -> `src/docla/render/library/`; `all_manifests()` merges `load_manifests()` and `load_manifests(library_dir())`, a duplicate name raises `ManifestError`; `ComponentManifest` gains optional `fixture: str | None` and `variants: list[str]`; `assemble` copies library `.typ` files into `dest/components/`; `load_chooser()` default manifests become `all_manifests()` | `load_manifests`, `assemble`, `load_chooser`, `_check_pairs` | B2.01 | none | Judge with a temporary library: `load_manifests()` still returns the four (stays); `all_manifests()` adds library ones; duplicate rejected; assembled folder holds both; chooser accepts a library component |
| B2.03 | Component harness and golden facts | `tests/test_components.py` (not a judge) iterates `all_manifests()`: each manifest with a `fixture` renders, every chooser component exists and is labelled, every doctype intent is in the chooser; `scripts/golden_facts.py <name>` writes `tests/fixtures/components/<name>.facts.json` (marks and word boxes per role); the harness compares within 0.5 pt, same roles, same counts (DESIGN 16.2, 16.3) | `swatch`, `layout_facts`, `all_manifests`, `load_chooser`, `load_doctypes` | B2.02 | none | Judge: the harness module exists, fails on a temp component whose golden differs by more than 0.5 pt, passes within tolerance |
| B2.04 | Section content in the composition | `ComposedSection.content: dict[str, Any]` holding `data` (Section.data), `image` (kit path or ""), `citations` (per item `[{key, locator}]`), `icons`; `_main_typ` calls `#name(comp.sections.at(i).props + comp.sections.at(i).content)`; props unchanged | `compose`, `_compose_section`, `_main_typ` | B2.02 | none | Judge: props keys exactly as pinned (stays); content carries data and locators; a component reading `sec.data` compiles; composition JSON round-trips (stays) |
| B2.05 | Images in the kit | `compose(doc, chooser=None, *, assets: list[Path] = [])` resolves `image=` against each folder in order (CLI passes `<file dir>/assets` then `<theme>/assets`); `assemble` copies each resolved image to `dest/assets/<sha256[:12]>.<ext>` (png, jpg, svg) and sets `content.image` to `/assets/...`; an unresolved image raises `ComposeError` naming the file and the folders | `compose`, `assemble`, `Theme.root` | B2.04 | none | Judge generates PNGs with Pillow at test time (nothing committed); missing image error names file; same bytes give same kit path |
| B2.06 | Show overflow clearly | `fit-box` clips its body (`clip: true`) and, when `need > have`, draws a 3 pt bar in `colour("accent")` along the inside of the bottom edge; marks unchanged | `render/lib/marks.typ` | B2.01 | none | Judge: m1_6 D4 shapes hold (one fit mark, wrap height 40) (stays); overflowing bullets render one page with no word box below the frame bottom when rasterised (words may remain in the PDF); `geo.text-fits` fail fixture still reports per-item `lines` (stays). Follow-up from M1 acceptance |
| B2.07 | Citations on the page | `render/lib/cite.typ` `cite-keys(citations)` renders `[S1 00:41]` after an item body in `colour("muted")` at the item's size; `statement`, `bullets`, `callout` and every library component draw item citations from `content.citations` | B2.04 `content.citations`, M1 components | B2.04 | none | Judge: a cited bullet's PDF words contain `[S1` and `00:41]`; positions of m1_7 marks hold (stays); clean SLIDES still `no findings` (stays). Doc paragraphs already print their bracket text (stays). Follow-up from M1 acceptance |
| B2.08 | cover | Intent `cover`. Title (display, large), subtitle from `paragraphs[0]`, accent panel band; capacity `title_words [1,12]`, `paragraphs [0,1]` | conventions, `slide-title` variant | B2.03, B2.07 | none | Template D1 to D6 |
| B2.09 | agenda | Intent `agenda`. Numbered items, capacity `items [2,8]`, `item_chars [3,60]` | conventions | B2.08 | none | Template |
| B2.10 | chapter-break | Intent `chapter-break`. Title plus optional number from `paragraphs[0]`, on `surface-alt` or `dark` fill with `on-dark` text | conventions | B2.09 | none | Template; palette clean |
| B2.11 | cards | Intent `parallel-set`: `when {count: [2,4]}` -> `cards`, default `bullets`. One card per item, head plus body | conventions | B2.10 | none | Template; the `source.citations-resolve` and `source.empty-section` fixtures (intent `parallel-set`) still give their findings (stays) |
| B2.12 | two-column | Intent `comparison` default entry. Two columns from items split in half, or from paragraphs | conventions | B2.11 | none | Template |
| B2.13 | comparison | Intent `comparison`: `when {count: [2,3]}` -> `comparison`, ahead of the two-column default. One column per item, head as column title, `sub` as rows | conventions | B2.12 | none | Template |
| B2.14 | key-figures | Intent `key-numbers`: `when {count: [3,4]}` -> `key-figures`, default `bullets`. Head is the figure (role `figure-value`, style `figure`), body the caption (`figure-caption`); capacity per DESIGN 8.1 | conventions | B2.13 | none | Template |
| B2.15 | quote | Intent `quote`. Quote from `paragraphs[0]`, attribution from `source_line` (role `source`) | conventions | B2.14 | none | Template |
| B2.16 | image-with-text | Intent `image-text`: `when {has_image: true}` -> `image-with-text`, default `bullets`. Image left half (role `image`), title and items right | B2.05 | B2.15 | none | Template with a generated PNG |
| B2.17 | full-image | Intent `full-image`: `when {has_image: true}` -> `full-image`, default `statement`. Image fills `full-frame`, optional caption | B2.05 | B2.16 | none | Template |
| B2.18 | chart (bar and column) | Intent `chart`: `when {has_data: true}` -> `chart`, default `bullets`. `render/lib/chart.typ` draws from `data: {type: bar|column, categories: [...], series: [{name, values}]}` (1 to 4 series) with Typst rectangles: elements `chart-plot`, `chart-mark` (one per bar), `chart-label`, `chart-legend`, `figure`, `figure-source`; colours from `chart.categorical`; unknown `type` draws a visible "chart type not supported" notice (DESIGN 9.6) | B2.04 `content.data` | B2.17 | none | Template; bar lengths proportional to values within 0.5 pt (judge reads marks); line, donut, stacked are after v0.1 (section 8, Q6) |
| B2.19 | table | Intent `table`: `when {has_data: true}` -> `table`. `data: {columns: [...], rows: [[...]]}`; header row role `table-header`, cells `table-cell`, frame `figure`, source `figure-source`; capacity `columns [2,6]`, `rows [1,10]` | B2.04 | B2.18 | none | Template |
| B2.20 | timeline | Intent `chronology` (not `timeline`, section 8 Q1). Items in order, head is the date, body the event, on a horizontal rule | conventions | B2.19 | none | Template; `timeline` intent still unknown for slides (stays) |
| B2.21 | process | Intent `process`. 3 to 6 steps with arrows, head plus body | conventions | B2.20 | none | Template |
| B2.22 | matrix | Intent `matrix`. Exactly 4 items in a 2x2 grid; optional axis labels from `data: {x: ..., y: ...}` | conventions | B2.21 | none | Template |
| B2.23 | people | Intent `people`. 2 to 6 people: head is the name, body the role | conventions | B2.22 | none | Template |
| B2.24 | contact | Intent `contact`. Title plus items as contact lines | conventions | B2.23 | none | Template |
| B2.25 | closing | Intent `closing`. Closing statement plus optional `spoken` line | conventions | B2.24 | none | Template |
| B2.26 | Gallery deck | `tests/fixtures/slides/gallery.md` uses every slides intent once (cover first, closing last); `scripts/build_gallery.py` builds it with the neutral theme | all component pieces, `docla build` | B2.25 | none | Judge: the gallery parses, `docla check` exits 0 with no error findings, every library slides component is used. **M2 acceptance for slides: owner looks at the gallery pages (O1)** |

Not in B2: icons and the icon-list variant, logo placement (both need licensed assets; after v0.1, section 7); doc
components (M6b); migrating `statement` and `bullets` to `type-style` (frozen sizes; after v0.1).

### B3. M2 rule catalogue minus semantic (19 pieces)

DESIGN 10.5 adapted to existing ids. Already done (stays): `source.citations-resolve`, `source.empty-section`,
`source.intent-known`, `geo.text-fits`, `geo.in-safe-area`, `geo.min-font`, `geo.palette`. Moved elsewhere:
`source.fact-support` to M3 (needs evidence), `pix.blank-page` and `pix.contrast` to M4 (18.2 places the pixel tier
there), `geo.page-fill` and `geo.column-balance` to M6c (document rules), `geo.logo` after v0.1 (needs a logo asset),
`sem.*` to M4 and M6c.

Rules for every B3 rule piece:
- New rules go in new lists (`docla.checks.<module>.RULES`) appended by `catalogue.all_rules()` after the existing ones;
  `m1_rules()` and `source.RULES` stay unchanged.
- Silent on the clean texts of section 2 at every severity, and no `error` on the `geo.text-fits` fail fixture's section
  that would block `geo.text-fits` (the engine blocks later tiers on a section with an error).
- Each judge runs the rule through `docla check` on its fx pair and through `run_checks` directly, and re-runs
  m1_17 D3 and theme_in_builds D2 clean texts expecting `no findings` (stays).

DSL primitives (DESIGN 10.4) needed in v0.1, and where: `select` and `all-of`/`any-of`/`not` (B3.02), `text-pattern`
(B3.04), `font-family` (B3.13), `image-dpi` (B3.15), `adjacent` (B3.16), `sequence` (B3.18), `contrast` (M4.02),
`page-fill` (M6c.03). Existing kinds keep their names: `fits`, `font-size`, `colour-in-set`, `in-safe-area` (stands for
`bbox-in-region` with region `safe-area`). After v0.1: `gap-between`, `align`, `ratio`, `count-per`.

| Key | Piece | Scope | Builds on | Dep | New dep | Fixtures and acceptance |
|---|---|---|---|---|---|---|
| B3.01 | Rule scope and check context | `Scope` gains `components: list[str] | None`, `intents: list[str] | None`; `Rule` gains `loop: Literal["micro","macro","both"] = "both"`; `CheckContext` gains `composition: Composition | None = None` and `final: bool = False`; `_applies` honours `scope.components/intents` through the composition; `make_finding` gains optional `severity`; `docla check` passes the composition and gains `--final`; schemas regenerated | `docla.model.rules`, `checks.engine`, `cli._check` | B2.26 | none | Judge: a rule scoped to `components: [bullets]` fires only on bullets sections; existing six rules unchanged (stays); `docs/schemas` current |
| B3.02 | DSL selector and boolean kinds | `docla.checks.dsl`: `select(ctx, spec) -> list[Selected]` over words, shapes, sections by `kind`, `role`, `section_intent`, `component`; registered kinds `all-of`, `any-of`, `not` that run sub-checks from `rule.check["checks"]` | B3.01 | B3.01 | none | Judge with synthetic `LayoutFacts`: selection by role and component; `not` inverts; no rule ids added to the catalogue |
| B3.03 | Theme rule files | `docla.theme.rules.load_theme_rules(theme) -> list[Rule]` from `rules/{ingested,authored,learned}/*.yaml`; lint: provenance present, check kind registered, ids unique across catalogue and theme, `origin` matches folder (`ingested`, `manual`, `feedback`); `docla check` runs `all_rules() + load_theme_rules(theme)` | `Rule`, `CHECKS`, `load_theme` | B3.02 | none | Judge with a theme copy holding one authored DSL rule: it fires; a rule without provenance or with an unknown kind fails with the file named; neutral has no rule files (stays clean) |
| B3.04 | source.title-label | `text-pattern` kind (`regex`, `must_match`/`must_not_match`, `field`); rule `source.title-label`: a title is not a question (ends `?`) and not a teaser (ends `...` or the ellipsis character); error, redraft | B3.02 | B3.03 | none | fx: fail title "What did the workshop find?", pass "What the workshop found" |
| B3.05 | source.banned-terms | Voice `banned` list matched case-insensitively on word boundaries in title, items, paragraphs (not note, spoken); error, redraft; message names the term | `load_voice`, B3.04 `text-pattern` | B3.04 | none | fx: fail uses "leverage", pass does not |
| B3.06 | source.terminology-drift | `Voice` gains `terminology: list[{preferred: str, avoid: list[str]}]`; neutral adds `{preferred: customer, avoid: [client]}`; warning when an avoided word appears in section text; message names the preferred word; brief card gains a `Preferred:` line (sorted) | `Voice`, `brief_card` | B3.05 | none | fx: fail "the client agreed", pass "the customer agreed"; brief card with no terminology unchanged (stays: test_m2_brief_card) |
| B3.07 | source.capacity | `docla.render.components.MEASURES: dict[str, Callable[[Section], int]]` for `title_words`, `items`, `item_chars`, `paragraphs`, `columns`, `rows`, `categories`, `series`; rule `source.capacity` reports **maxima only**, severity **warning**, redraft, `measured: {measure, value, max}` (section 8, Q4) | manifests via `all_manifests()`, composition | B3.06 | none | fx: fail bullets with 7 items, pass with 5; `geo.text-fits` fail fixture still reports `error geo.text-fits` (stays) |
| B3.08 | source.gap-present and final mode | `[GAP: ...]` in any text field: warning in draft, error with `--final` | B3.01 `final`, `make_finding(severity=)` | B3.07 | none | fx: fail with a GAP, pass without; judge runs fail side in draft (warning, exit 0) and `--final` (error, exit 1) |
| B3.09 | source.uncited-figure | A number (DESIGN 11.5 `NUM` pattern) in an item head or body with no citation: warning in draft, error with `--final` | B3.08 | B3.08 | none | fx: fail "drops 12% of readings" uncited, pass cited; text-fits and in-safe-area pass fixtures still exit 0 (stays) |
| B3.10 | source.outline-conforms | `docla.doctypes.conformance(doc, doctype) -> list[Gap]` (required sections present, order, repeat bounds, by the `section=` attribute); rule in a new `catalogue.document_rules()`, **not** in `all_rules()`; `docla check --outline` runs it (section 8, Q5) | `load_doctypes`, `OutlineEntry` | B3.09 | none | fx: fail pitch-deck without `ask`, pass with opener, content, ask; judge runs both with `--outline`; plain `check` of clean SLIDES still `no findings` (stays) |
| B3.11 | Parser findings in the catalogue | `catalogue.parser_rules()` returns `Rule` records (title, severity, remedy) for the parser's ids `source.appearance-in-source` (engine), `source.unknown-attribute` (report), `source.parse-error`, `source.missing-intent`, `source.invalid-format`; parser behaviour (stays) | `parser.SEVERITY`, `catalogue` | B3.10 | none | fx pairs for `source.appearance-in-source` (`color="red"`) and `source.unknown-attribute` |
| B3.12 | source.image-resolves | Source-tier rule: `image=` names a file found in the asset folders (B2.05); `docla check` reports it instead of stopping (compose falls back to the source tier as now) | B2.05, `cli._check` | B3.11 | none | fx: fail `image="missing.png"`, pass with a fixture PNG committed with a licence note (own work, generated by `scripts/make_fixture_images.py`) |
| B3.13 | geo.fonts | `font-family` kind; rule `geo.fonts`: every word's font is a theme family (PDF names such as `ABCDEF+Inter-Regular` normalised by stripping the subset prefix and style suffix); error, engine | `PlacedWord.font`, `Tokens.type.families` | B3.12 | none | fx: fail `main.typ` setting font to Typst's embedded "Libertinus Serif", pass with Inter |
| B3.14 | Image facts | `PageFacts.images: list[ImageFact(box, native_w, native_h, dpi_x, dpi_y)]` from pdfplumber `page.images`; `LayoutFacts.images: list[PlacedImage]` with role and section; words and shapes unchanged (stays) | `PdfPlumberFacts`, `join` | B3.13 | none | Judge: an image-with-text swatch yields one placed image with the right section and dpi within 1% |
| B3.15 | geo.image-dpi | `image-dpi` kind; `Tokens` gains optional `imagery: {min_dpi: float}` (neutral 150); error, restructure | B3.14 | B3.14 | none | fx: fail a 60 px wide PNG on `full-image`, pass a 2000 px one (generated, licence note) |
| B3.16 | geo.figure-source | `adjacent` kind (`a`, `b` selectors, `within_pt`, `edge`); rule: element `figure-source` sits within 24 pt below its `figure`; warning, tune; components without a source line pass | B3.02, B2.18, B2.19 | B3.15 | none | fx: fail a chart whose source line is pushed away (fixture `main.typ`), pass the chart fixture |
| B3.17 | geo.chart-labels | Code check: each `chart-label` lies inside or within 4 pt of its `chart-mark`; bar lengths proportional to `content.data` values within 1 pt; error, engine | B2.18 marks, B3.01 composition | B3.16 | none | fx: fail `main.typ` with a label 40 pt off its bar, pass the chart fixture |
| B3.18 | Deck pace rules | `sequence` kind (`over: sections`, `window`, `forbid_repeat` / `require_change`); rules `deck.no-component-three-running` (same component 3 in a row) and `deck.pace-every` (n 6: a change of component within every 6 slides); slides, warning, restructure, `loop: macro` | B3.01 composition | B3.17 | none | fx: fail four `bullets` slides, pass alternating components |
| B3.19 | Neutral gold corpus and `docla theme test` | `themes/neutral/exemplars/gold/deck.md` and `report.md` (working files, no PDFs); `docla theme test [--theme DIR]`: rule lint (B3.03), chooser coverage (every component exists and is labelled, every doctype intent known), every component fixture renders, gold corpus `check --final` has zero errors | B2.03 harness, B3.03, `load_doctypes` | B3.18 | none | Judge: exits 0 on neutral; a theme copy with a broken chooser entry exits 1 naming it. **M2 acceptance: owner looks at gold pages and fx renders (O1)** |

### M3. Writer and micro loop, slides (16 pieces)

DESIGN 11.1 to 11.3, 11.5, 11.6, 11.8, 11.10, 14, 4.4, Appendix B.1, B.2, spike S4. Every Claude call goes through
`docla.agents.client.Claude` over a `Transport`. Tests use `FakeTransport` (returns canned response dicts keyed by
role) or replay a cassette when one exists. Agent modules: `docla/agents/{client,ledger,scheduler,prompts,gatherer,
planner,writer}.py`; loop modules: `docla/loop/{guards,router,micro,best_of,heal_log}.py`.

| Key | Piece | Scope | Builds on | Dep | New dep | Fixtures and acceptance |
|---|---|---|---|---|---|---|
| M3.01 | Claude client wrapper | `Claude(transport, ledger, models)` with async `call(role, schema, *, system, content, effort, max_tokens) -> T`; builds the request dict per DESIGN 14.3/14.4 (structured output for `schema`, `output_config.effort`, cache_control on the last stable system block); validates with `schema.model_validate_json`; one retry with the error appended; `AgentRefused`, `AgentTruncated`, `AgentInvalid`; `AnthropicTransport` (the only module importing `anthropic`, constructed only for live use) and `CassetteTransport(cassette)`; `image_block(png)` | `Cassette`, `Transport` | B3.19 | `anthropic` (MIT) | Judge with `FakeTransport`: parsed output; refusal and max_tokens raise; invalid then valid succeeds with 2 calls; request bytes identical for identical inputs. The builder checks request field names against the installed SDK's types offline and records them in `docs/decisions.md`; O4 confirms live |
| M3.02 | Project config, ledger, budgets, doctor | `docla.config.load_project_config(dir) -> ProjectConfig` from `docla.toml` (`[loop]`, `[budget]`, `[models]`, `[prices]` as DESIGN 11.8; `tomllib`); `Ledger.add(role, model, usage)` computes USD from prices, appends to a JSONL path; `BudgetExceeded` at `max_usd_per_document`; `docla init DIR` writes `docla.toml` and `sources/`; `docla doctor` reports whether an Anthropic credential is set (never prints it) | `cli`, `doctor` | M3.01 | none | Judge: defaults when no file; cost arithmetic; budget stop; doctor line present with and without `ANTHROPIC_API_KEY` |
| M3.03 | Scheduler | `Scheduler(max_concurrency=4, sleep, rng)`: semaphore, exponential backoff with jitter on 429 and 5xx, honours `retry-after`, gives up after N tries; injected sleep and rng for tests | M3.01 | M3.02 | none | Judge: concurrency never exceeds cap; retry-after respected; deterministic backoff sequence with seeded rng (DESIGN 4.4) |
| M3.04 | Prompt kit | `docla/agents/prompts/` text files; `system_blocks(role, theme, brief) -> list[dict]` with the shared header of DESIGN 14.6 byte-identical across roles, voice block, brief card, cache_control on the last stable block; volatile content separate | `brief_card`, `load_voice` | M3.03 | none | Judge: header identical across roles; data-not-instructions sentence present; stable blocks sorted and free of timestamps |
| M3.05 | Fact guard and kept facts | `docla.loop.guards.FactGuard(evidence)` callable as `FactGuard` (`(doc, section) -> bool`) with `.unsupported`; per field, citations checked separately, number words normalised, `calc:` note recomputed for sum, difference, ratio, percentage (S4 decision 2, DESIGN 11.5); `kept_facts(before, after) -> list[str]`; rules `source.fact-support` (error, redraft) and `source.facts-kept` (error, redraft) in a new list | `apply_patch` hook, S4 code in `docs/spikes/code/s4/` | M3.04 | none | fx: `before.md`/`after.md` pairs for each rule (invented "14%", lost "North Sea"); "month one" vs "month 1" accepted |
| M3.06 | Source extraction | `docla.sources.extract(project) -> list[Extracted]`: `sources/*.pdf` via pdfplumber with `<!-- page N -->` markers, `.txt`, `.md`, `.vtt` (timestamps kept) into `extracted/<name>.md`; never truncates; stable source keys S1, S2... by file name order | pdfplumber | M3.05 | none | Judge on generated PDF and VTT fixtures: markers, keys, idempotent |
| M3.07 | Gatherer | `gather(claude, extracted) -> list[Fact(text, source_key, locator)]`: citations-enabled document blocks, cited spans to `Fact` in code (DESIGN 14.5), chunked | M3.01, M3.06 | M3.06 | none | Judge with a fake response carrying `char_location` and `page_location` citations; locators `p.4` and `00:41` |
| M3.08 | Planner | `plan(claude, facts, doctype, brief) -> Outline` (B.8): outline lines with intent from the chooser's intents, at most 2 questions, gap marks; `outline_to_document(outline, front) -> Document` with ids stamped | `load_doctypes`, `Chooser.knows`, `stamp`, `serialise` | M3.07 | none | Judge with fake: intents outside the chooser rejected with one retry; at most 2 questions kept |
| M3.09 | Writer draft | `draft(claude, job, facts, brief, exemplar) -> SectionDraft` (B.1; items with `priority`, citations, `[GAP: ...]`); `draft_to_section(draft, job) -> Section` | M3.04, `ComponentManifest.capacity_text` | M3.08 | none | Judge with fake: citations become `Citation`; gaps kept; capacity text in the prompt |
| M3.10 | Writer repair | `repair(claude, section, findings, history, brief, images=None) -> Patch` (B.2): findings rendered per element (lines used, characters that free a line, from `geo.text-fits` `measured.items`), compact history, "a fact a title cannot hold may move into an item" (S4 decision 3); returns `set_fields` only | M3.09, `Patch` | M3.09 | none | Judge with fake: prompt names item numbers and cut sizes; non-`set_fields` ops rejected |
| M3.11 | Router and deterministic fixes | `route(findings, section) -> Plan` (DESIGN 11.3, locks respected); `Chooser.alternates(section, fmt, index, total) -> list[str]`; `deterministic_fix(state, job) -> Section | None` (switch to the next alternate component, `because` set) | `Chooser`, `Remedy.class_` | M3.10 | none | Judge: locked section's redraft goes to report; engine findings never loop; alternate chosen in chooser order |
| M3.12 | Micro loop | `write_section(job, ctx) -> SectionResult` per DESIGN 11.2: `evaluate` = swatch + `run_checks` (micro rules only), Φ = 10e + 3w + 1i, accept guard (strict decrease, `cleared` fingerprints, oscillation, stall, DESIGN 11.6), attempts budget, residual | `swatch`, `run_checks`, M3.05, M3.10, M3.11 | M3.11 | none | Judge with a fake writer on the `geo.text-fits` fail fixture: clears in at most 3 attempts; a regression candidate is rejected; stall jumps to best-of-N hook |
| M3.13 | Best-of-N | `best_of_n(state, job, ctx, n=3)`: N strategy prompts, swatches in parallel, score `(blocking, warnings, -fact_preservation, edit_distance)` | M3.12 | M3.12 | none | Judge with fake candidates: lowest score wins; a candidate losing facts loses |
| M3.14 | Heal log and resume | `HealLog(path)` writes DESIGN 11.10 lines with before/after crops (`crop`); `resume(run_dir) -> set[section_id]` so a restarted build skips finished sections without repeating paid calls (DESIGN 4.4) | `crop`, M3.12 | M3.13 | none | Judge: lines validate; a killed run resumes with zero calls for finished sections (fake transport call count) |
| M3.15 | `docla write` command | `docla write FILE`: gather, plan (writes the outline and stops unless `--approve`), draft sections in parallel through the scheduler, micro loop, write the working file through `apply_to_file`, build the PDF; cost estimate and confirmation above 40 sections (DESIGN 4.4); running cost printed | M3.01 to M3.14 | M3.14 | none | Judge end to end with `FakeTransport` on a 3-source project: outline stop, then a clean deck; never constructs `AnthropicTransport` without `DOCLA_LIVE=1` |
| M3.16 | Heal eval set and runner | `tests/fixtures/heal-eval/` 40 seeded sections (overflow, banned term, drift, missing citation, long title) across components with known facts; `docla eval heal [--live]` writes `evals/RESULTS.md` (% cleared in at most 3 attempts, mean attempts, cost, facts kept); offline mode uses a fake writer | M3.12, M3.15 | M3.15 | none | Judge: 40 fixtures parse and each fails its rule before repair; offline run writes RESULTS.md. **Live run is owner step O5 (M3 acceptance)** |

### M4. Look, critic, macro loop, slides (12 pieces)

DESIGN 11.4, 11.7 to 11.9, 15.1 to 15.3, 18.2 M4. Critic settings (model tier, image size, corroboration default) wait
on spike S3 (O6); until then the critic runs with DESIGN 11.8 defaults and every rubric item is advisory (`info`)
because no item has measured precision (DESIGN 11.4 rule 5).

| Key | Piece | Scope | Builds on | Dep | New dep | Fixtures and acceptance |
|---|---|---|---|---|---|---|
| M4.01 | Pixel tier and pix.blank-page | `CheckContext.pages_png: list[Path]` and `page_png(n)`; engine runs pixel checks only when rasters are present; `docla check` rasterises; `pix.blank-page`: ink coverage below threshold on a page whose components are not `chapter-break`/`cover`; error, restructure | `PdfiumRasteriser`, engine tiers | M3.16 | none | fx: fail a page with one tiny word, pass a statement slide; clean texts still `no findings` (stays) |
| M4.02 | pix.contrast | `contrast` kind: text colour (facts) against the background sampled from the raster around each word; ratio below `colour.contrast_min`; error, engine | M4.01 | M4.01 | none | fx: fail `muted` text on `dark` fill, pass `on-dark` |
| M4.03 | Contact and spread sheets | `contact_sheet(pngs, labels) -> png` (slides, page numbers and section ids) and `spread_sheet` (docs, facing pages); long side at most 1568 px | Pillow, `PdfiumRasteriser` | M4.02 | none | Judge: size bound, labels present, deterministic bytes |
| M4.04 | Rubric | `docla.theme.rubric.load_rubric(theme) -> Rubric` from `rubric/visual.yaml` (DESIGN 11.4) with `applies(format, component, intent)`; neutral items `sem.focal-point`, `sem.repetition`, `sem.balance`, `sem.reader-words` (no `sem.brand-feel` until gold crops exist) | `Theme` | M4.03 | none | Judge: filter by component; unknown keys rejected |
| M4.05 | Critic agent | `critique(claude, images, rubric_items, engine_findings, regions) -> list[Finding]` (B.6): closed vocabulary (unknown ids dropped), bbox 0..1000 mapped to page points and anchored to a section region else `info`, no repeats by fingerprint, findings `tier="semantic"`; images downscaled to at most 1568 px | M3.01, M4.04 | M4.04 | none | Judge with fake reports: invented id dropped; unanchored fail downgraded; duplicate of an engine finding dropped |
| M4.06 | Corroboration and calibration gate | Second call with shuffled rubric order; `corroborated` when both fail with overlapping bbox or a deterministic finding agrees; `rubric/calibration.yaml` precision per item; items below 0.8 or uncalibrated forced to `info`; `loop.act_on_uncorroborated` honoured | M4.05, M3.02 config | M4.05 | none | Judge with fakes: one-call fail is uncorroborated; calibrated 0.9 item keeps severity; missing calibration gives `info` |
| M4.07 | Versions and manifest | `docla.store`: `write_version(doc_path, doc, comp, pdf, facts, findings, pngs, heal) -> Version` into `<stem>.versions/vN/` (DESIGN 15.1); `Manifest` model (15.2, typst `0.15.1`); immutable except `state`, `sent_to`; `pages/pages.json` (page to sections, regions, findings) | `LayoutFacts`, `Finding` | M4.06 | none | Judge: two builds give v1 and v2; rewriting v1 refuses; manifest schema exported to `docs/schemas` |
| M4.08 | Look | `look(pdf, comp, ctx) -> Look` (raster, facts cached by PDF sha256 under `.docla/cache/facts/`, all deterministic tiers, critic only on pages with no blocking deterministic finding and changed swatch hash, `could_not` listed) | M4.01 to M4.07 | M4.07 | none | Judge with fake critic: a page with overflow is never sent to the critic; cache hit on unchanged PDF |
| M4.09 | Summariser | `summarise(claude, sections) -> SectionDraft` for outline entries with `fill: summary` (agenda, executive summary); may contain no new facts (fact guard against section texts) | M3.04, M3.05 | M4.08 | none | Judge with fake: a new number is rejected |
| M4.10 | Macro loop | `build_document(doc, ctx) -> Version` per DESIGN 11.7: micro loop per section in parallel, summaries last, rounds at most 2, `validate` runs `document_rules()` (B3.10) and macro rules (`deck.*`), route, execute affected sections, full rebuild, `no_progress` stop; engine findings listed once | M3.12, M4.08, M4.09, B3.10, B3.18 | M4.09 | none | Judge with fake writer: seeded deck (four bullets in a row plus an overflow) clean within 2 rounds; engine finding not retried |
| M4.11 | Ship gate | `ship_gate(version) -> list[str]` (DESIGN 11.9); `docla build --final` and `docla ready VERSION_DIR [--force --reason TEXT]` (force recorded in the manifest); `docla build` without flags keeps its current outputs (stays) | M4.07, M4.10 | M4.10 | none | Judge: gaps refuse final; unacknowledged uncorroborated errors refuse; force without reason refused |
| M4.12 | Critic eval runner | `tests/fixtures/critic-eval/` format (`crops/*.png` plus `labels.yaml` of rubric id and verdict); `scripts/mutate_crops.py` makes synthetic failures from clean swatches (cramped, off-balance, repeated); `docla eval critic [--live]` reports precision and recall per item and two-run agreement and writes `rubric/calibration.yaml` | M4.05, M4.06 | M4.11 | none | Judge offline with a fake critic: metrics computed; calibration file written. **Live run and labelling: O7 (M4 acceptance)** |

### M5. Visualiser MVP, slides (13 pieces)

DESIGN 13, 18.2 M5, C.6. Python side first (M5.01 to M5.07 need no npm). Web pieces (M5.08 to M5.13) need O9 merged.
Web app in `web/` (Vite, React, TypeScript, TanStack Query), its own `package.json` (the root `package.json` is the npm
name placeholder and stays). `docla serve` serves `web/dist` when built; packaging the built app into the wheel is M11.

| Key | Piece | Scope | Builds on | Dep | New dep | Fixtures and acceptance |
|---|---|---|---|---|---|---|
| M5.01 | Server skeleton and security | `docla.server.app.create_app(project, token) -> FastAPI`; `docla serve DIR [--port]` binds 127.0.0.1, random per-launch token in the URL fragment, every request checks token header, `Host` and `Origin` (DESIGN 13.9, 17.4); `GET /api/projects` | `cli` | M4.12 | `fastapi` (MIT), `uvicorn` (BSD-3), `httpx` (BSD-3, test) | Judge with `TestClient`: wrong Host or Origin 403; missing token 401 |
| M5.02 | Event bus and SSE | `EventBus.publish/subscribe`; `GET /api/events` as in DESIGN C.6 with keepalive; event types of 13.7 | M5.01 | M5.01 | none | Judge: subscriber receives a published `doc.changed`; keepalive after timeout (injected) |
| M5.03 | Document API | `GET /api/docs/{doc}`, `PATCH .../sections/{id}` (human `set_fields`, `owner="human"`, 409 with current document on stale `base_rev`), `POST .../sections`, `DELETE .../sections/{id}`; single writer through `apply_to_file`; undo inverse stored in oplog | `apply_to_file`, `IdStore` | M5.02 | none | Judge: stale rev 409; owner set; `doc.changed` published |
| M5.04 | Jobs | `JobRunner` (asyncio tasks, `job.started/progress/finished`); `POST .../build {mode}` runs the macro loop on a snapshot rev and marks the version stale if rev moved; `POST .../sections/{id}/redraft {ask}` runs the micro loop with the ask | M4.10, M3.12 | M5.03 | none | Judge with fake transport: build job yields a version; edit during build marks it stale |
| M5.05 | Versions API | `GET .../versions`, `.../versions/{n}/pages` (pages.json), `.../page/{k}.png` with ETag = page hash, `.../heal`, `POST .../versions/{n}/ready` (ship gate) | M4.07, M4.11 | M5.04 | none | Judge: ETag 304; gate reasons returned |
| M5.06 | Fast preview | After a PATCH: swatch of that section (or a full draft render when the section is flow-sensitive), findings, PNG, pushed as `section.state` and `look.progress` | `swatch`, `run_checks`, M5.03 | M5.05 | none | Judge: event within 2 s on the bullets fixture (generous bound for CI); new finding after an overflowing edit |
| M5.07 | File watcher | Stdlib polling watcher on `<doc>.md`: valid external edit becomes a human patch diffed by section id; invalid keeps the last good document and publishes parse findings | `parse`, M5.03 | M5.06 | none | Judge with injected clock: external edit appears as `doc.changed {by: "human"}` |
| M5.08 | Web scaffold (needs O9) | `web/` Vite + React + TS + TanStack Query, API client with token, `vitest` + `jsdom`; `npm run build` to `web/dist`; server serves it | M5.01 | M5.07, O9 | npm: vite, react, react-dom, typescript, @tanstack/react-query, vitest, jsdom, @testing-library/react | Judge (Python) runs `npm ci && npm test` and asserts `web/dist/index.html` after build; lockfile has no banned word |
| M5.09 | Canvas and overlays | Page PNG plus `<svg viewBox="0 0 W H">` in points; section regions on hover, element outlines on click, finding badges; click selects the owning section; keyboard navigation | M5.05 pages.json | M5.08 | none | vitest: box at (40,120) maps to the same svg coordinates; click selects section |
| M5.10 | Outline and field editor | Content tab (title, items head/body/sub, paragraphs, note, spoken, source line, data table), debounced PATCH with base_rev and 409 rebase; outline view: reorder, add, delete, change intent | M5.03 | M5.09 | none | vitest with mocked API |
| M5.11 | Findings, activity, needs you | Findings tab with rule title and provenance; activity bar from SSE; needs-you queue (residual, engine, ask, gaps); severity never by colour alone | M5.02 | M5.10 | none | vitest |
| M5.12 | History and versions | Heal replay scrubber from heal.jsonl with before/after crops; versions list, side-by-side compare, mark ready | M5.05 | M5.11 | none | vitest. **M5 acceptance: owner edits a bullet and sees render and finding in about 1 to 2 s; external edit appears (O10)** |
| M5.13 | CI web job (owner merge) | Add an npm build and test job to `.github/workflows/ci.yml` | M5.08 | M5.12, O9 | none | Protected path; owner merges; not in an overnight batch |

Playwright UI tests (DESIGN 16.2) need browser downloads from a domain outside the sandbox; v0.1 uses vitest component
tests and the owner's hands-on check. Playwright is in M11 (section 8, Q15).

### M6. Documents (42 pieces in four sub-batches)

DESIGN 18.3, spikes S1b and S8. Doc components follow the B2 conventions with format `doc`: flowing, not fixed frames;
fixed-size blocks (callout, sidebar, key-figures strip) still use `fit-box` where they cannot break. Doc component names
differ from slide names because a manifest has one format.

#### M6a. Flow engine and page model (7)

| Key | Piece | Scope | Builds on | Dep | New dep | Fixtures and acceptance |
|---|---|---|---|---|---|---|
| M6a.01 | Page model options | `PAGE_SIZES` gains `letter`; `Page` gains `safe_footer`; front matter `paper: a4|letter` and `columns: 1|2` override the theme's doc page (neutral stays one column, section 8 Q7); `page-setup(format, body, paper: auto, columns: auto)` named args in generated theme.typ; gutter from tokens | `render_theme_typ`, `Page`, `_main_typ` | M5.07 | none | Judge: Letter media box 612x792; two columns with gutter; `page-setup.with("doc")` unchanged (stays) |
| M6a.02 | Section model: placement | `Section.place: Literal["top","foot","here"] | None`; parser and serialiser support `place=`; round-trip property holds; schemas regenerated | parser, serialiser, model | M6a.01 | none | Judge: parse/serialise identity with `place`; appearance attributes still rejected (stays) |
| M6a.03 | Running furniture | Running header (document title, current H1) and footer (page number) outside section marks; first-page variant (none on cover); inside `safe_footer` | M6a.01 | M6a.02 | none | Judge: page numbers 2..N present; furniture words have `section_id` None; `geo.in-safe-area` silent (stays) |
| M6a.04 | Flow primitives | Real `heading` levels: chapter-opener H1, section titles H2, body paragraphs starting `### ` render as H3; lists from items in body; block quotes from paragraphs starting `> ` (not `> note:` etc.); code blocks from `Section.code`; widow and orphan costs left at Typst defaults and headings sticky (S8 decision 2) | `body.typ` (unchanged for M1 marks), a new library `prose` helper | M6a.03 | none | Judge: H3 present in outline query; a heading never last line of a column on a forced fixture |
| M6a.05 | Floats | `span: column|full` and `place: top|foot|here` drive `place(..., float: true, scope: column|parent)` around figure-like components; floats flushed before a chapter opener so they never leave their chapter; caption and source inside the float | M6a.02 | M6a.04 | none | Judge: full-span float mark width equals text width; float stays before the next chapter's start mark |
| M6a.06 | Long tables, footnotes, cross-references | Long tables break with `table.header(repeat: true)`; footnotes from `[^: text]` in item or paragraph text; cross-references `[see: <section-id>]` rendered as "see Figure N" or "see section N"; `page="new"` honoured (section 8, Q8) | parser text fields, M6a.05 | M6a.05 | none | Judge: header row on every table page; footnote at page foot; unknown xref target renders a visible marker |
| M6a.07 | Flow regions | `LayoutFacts.regions: list[SectionRegion(section_id, boxes)]` with one box per column or page fragment from section start marks as cut points plus the assigned words (S1b decision 2); frames from `el` marks; re-run S1b checks on real doc components | `join`, `SectionMark` | M6a.06 | none | Judge: a section spanning a column break has two boxes; 100% of words assigned on a 4-page fixture |

#### M6b. Document component set (14)

Each row follows the component template (manifest, chooser entry, fixture, golden facts, capacity, render with the
neutral theme, `docla check` clean), with format `doc` and an A4 one- and two-column fixture.

| Key | Piece | Intent (doc) | Scope | Dep |
|---|---|---|---|---|
| M6b.01 | cover-doc | `cover` | Variants title-only, panel, image-top (`when has_image`); full-page image never chosen | M6a.07 |
| M6b.02 | contents | `contents` | Automatic contents from H1/H2 (Typst outline) with page numbers | M6b.01 |
| M6b.03 | chapter-opener | `chapter-break` | New page, H1, optional number and lead paragraph | M6b.02 |
| M6b.04 | key-figures-strip | `key-numbers` | 2 to 5 figures in a full-width strip, `fit-box` | M6b.03 |
| M6b.05 | figure | `chart`, `image-text` | Chart via `lib/chart.typ` (B2.18) or image, caption, source line (`figure-source`), float per M6a.05 | M6b.04 |
| M6b.06 | doc-table | `table` | Plain, banded, tag-table via `data.style`; long-table header repeat | M6b.05 |
| M6b.07 | sidebar | `sidebar` | Boxed aside on `surface-alt`, column width, non-breaking | M6b.06 |
| M6b.08 | pull-quote | `quote` | Large quote with attribution | M6b.07 |
| M6b.09 | timeline-doc | `chronology` | Vertical dated list | M6b.08 |
| M6b.10 | process-doc | `process` | Numbered steps | M6b.09 |
| M6b.11 | comparison-doc | `comparison` | Columns per item, rows from `sub` | M6b.10 |
| M6b.12 | people-card | `people`, `contact` | Name, role, contact lines | M6b.11 |
| M6b.13 | references | `references` | Lists `## Sources` (Composition gains `sources`), cited ones first | M6b.12 |
| M6b.14 | appendix-divider and back-cover | `appendix`, `closing` | Two small components, one piece | M6b.13 |

#### M6c. Document rules and flow repairs (14)

| Key | Piece | Scope | Builds on | Dep | New dep | Fixtures and acceptance |
|---|---|---|---|---|---|---|
| M6c.01 | Flow lines | `docla.facts.flow.lines(facts) -> list[Line(page, column, y, block_id, section_id)]` from PDF words plus block start marks in reading order (S8 method); re-run the S8 seeded set against the real body component | M6a.07 | M6b.14 | none | Judge: 12 of 12 seeded defects detectable, 0 false positives on the controls (from `docs/spikes/code/s8/`) |
| M6c.02 | geo.widow-orphan, geo.heading-at-foot | Detectors (theme prevents them; rules stay as checks); warning, tune | M6c.01 | M6c.01 | none | fx pairs: fixtures force zero widow cost in `main.typ` |
| M6c.03 | geo.page-fill | `page-fill` kind: near-empty page (under 15% of live area), blank head or tail; `measured.lines` = N for copyfit; ignore cover, chapter-opener, appendix-divider | M6c.01 | M6c.02 | none | fx: 2-line last page fails; full page passes |
| M6c.04 | geo.column-balance | Last-page columns differ by more than a quarter column; column hole; `measured.move_lines` | M6c.01 | M6c.03 | none | fx pair |
| M6c.05 | geo.float-placement | Float in mid-column (not top or foot); caption separated from its figure | M6a.05 | M6c.04 | none | fx pair |
| M6c.06 | geo.table-header-repeat, doc figure-source | Header row present on each page of a broken table; `geo.figure-source` scope extended to doc `figure` | M6a.06, B3.16 | M6c.05 | none | fx pairs |
| M6c.07 | geo.reading-order, geo.text-density | Reading order of section starts matches source order; text density per page above a theme threshold | M6c.01 | M6c.06 | none | fx pairs |
| M6c.08 | source.heading-hierarchy, source.contents-match | No skipped heading levels; contents entries match the headings | M6a.04, M6b.02 | M6c.07 | none | fx pairs |
| M6c.09 | source.xref-resolves | Every `[see: id]` names an existing section; error, redraft | M6a.06 | M6c.08 | none | fx pair |
| M6c.10 | Copyfit repair | Router maps `geo.page-fill` and `geo.column-balance` to a writer repair on the section before the break: "cut about N lines" with N from `measured` (S8 decision 3, DESIGN 11.7) | M3.10, M4.10 | M6c.09 | none | Judge with fake writer: near-empty last page cleared in at most 2 rounds |
| M6c.11 | Float tune and component change | Deterministic `tune`: change `span`/`place` of a float; switch to an alternate component | M3.11, M6a.05 | M6c.10 | none | Judge: mid-column float fixed without a model call |
| M6c.12 | Split and merge | Macro-only restructure within doctype `repeat` bounds; never on `lock: all` | M4.10, `OutlineEntry.repeat` | M6c.11 | none | Judge with fake writer: an overlong section split when the outline allows it, refused when it does not |
| M6c.13 | Doc micro loop and preview | Swatch for flow components on a column-width frame; `flow_sensitive(section)` decides swatch vs full draft render for fast preview | `swatch`, M5.06 | M6c.12 | none | Judge: doc section swatch reports one region; preview chooses full render for a section before a page break |
| M6c.14 | Doc rubric | Neutral rubric items `sem.spread-balance`, `sem.flow-gap`, `sem.component-misfit`, `sem.repetition` (docs: repeated chart pages are design, not a fault); spread sheets to the critic | M4.04, M4.03 | M6c.13 | none | Judge with fake critic; items advisory until calibrated (stays M4.06) |

#### M6d. Doctypes, PDF quality, editor, acceptance (7)

| Key | Piece | Scope | Builds on | Dep | New dep | Fixtures and acceptance |
|---|---|---|---|---|---|---|
| M6d.01 | Theme doctypes | `load_doctypes(theme: Theme | None = None)`: packaged set, then `themes/<t>/doctypes/*.yaml` overriding by name; with no theme the packaged two (stays); `docla check --outline` uses the theme's doctypes | `load_doctypes`, `load_doctype` | M6c.14 | none | Judge: neutral adds doctypes; `load_doctypes()` still exactly two (stays) |
| M6d.02 | Neutral doctypes I | `report` (full: cover, contents, chapters, references; overrides packaged in the theme), `whitepaper`, `fact-sheet` (one-pager) with outline, questions, checks, checklist; DESIGN 8.4 `pitch-deck` (cover, agenda, chapters, ask, close) as a theme override | M6d.01 | M6d.01 | none | Judge: each loads and every intent resolves |
| M6d.03 | Neutral doctypes II | `proposal`, `memo`, `assessment-report` | M6d.02 | M6d.02 | none | Same |
| M6d.04 | PDF output quality | Document title and language set from front matter (`set document(...)`, `set text(lang:)`), bookmarks from headings, alt text for figures from `Section` text, embedded fonts only; record in `docs/decisions.md` whether Typst 0.15.1 writes tagged PDF | M6a.04 | M6d.03 | none | Judge reads PDF metadata with pdfplumber/pypdfium2: title, lang, outline entries |
| M6d.05 | Multi-box overlays (web) | A section with several region boxes highlights all and selects as one; spreads in the filmstrip | M5.09, M6a.07 | M5.12, M6d.07, O9 | none | vitest |
| M6d.06 | Long-document outline (web) | Outline collapse by chapter; page filmstrip with spreads | M5.10 | M6d.05 | none | vitest |
| M6d.07 | Acceptance report | `tests/fixtures/doc/acceptance-report.md`: 12 pages, two columns, 6 charts, 2 long tables, footnotes; judge builds it, checks regions, seeds a near-empty last page and repairs it by copyfit with a fake writer, times a one-paragraph preview, runs the ship gate | all M6 Python pieces | M6d.04 | none | **M6 acceptance: owner looks at the pages and overlays (O12)** |

Piece counts: B2 26, B3 19, M3 16, M4 12, M5 13, M6 42 (M6a 7, M6b 14, M6c 14, M6d 7). Total 128. ROADMAP estimated about
71 for M2 to M6; the frozen-judge workarounds, the eval runners and the per-component split add the difference.

---

## 5. Owner steps

| # | Step | When | Gates | Cost |
|---|---|---|---|---|
| O0 | Settle or accept the defaults in section 8 | Before the coordinator shapes B2 | All shaping | none |
| O1 | Look at the B2 gallery pages, the B3 fixture renders and the gold corpus; merge the batch PRs | After B2 and B3 | M2 acceptance (18.2, 18.5) | none |
| O2 | Merge `loop/v0` into `main` through one reviewed PR per batch | After each batch | `main` stays the owner's | none |
| O3 | Confirm the licences of new dependencies in the PRs that add them (`anthropic`, `fastapi`, `uvicorn`, `httpx`, npm set) | M3.01, M5.01, M5.08 | AGENTS.md licence rule | none |
| O4 | Live smoke call: one structured-output call per role shape with `DOCLA_LIVE=1`, confirming request fields of M3.01 | After M3.01 merges | Cassette recording | cents |
| O5 | Record M3 cassettes (gatherer, planner, writer draft, writer repair) with `DOCLA_RECORD=1`, and run the live heal eval `docla eval heal --live` | After M3 | M3 acceptance: at least 90% cleared in 3 attempts, 99% facts kept | S4 measured $0.60 to $0.80 for 20 repaired sections (Opus, effort medium); 40 sections plus drafts is a few dollars (estimate). DESIGN 11.8 caps $5 per document |
| O6 | Spike S3, critic reliability: 8 hand-made defects, 3 model tiers, 2 image sizes, with and without 2-call corroboration; write `docs/spikes/S3-critic.md` | Before M4 acceptance; M4 code builds without it | M4.06 defaults (tier, image size, corroboration) | Not estimated in DESIGN; about 100 vision calls, my estimate $5 to $20 |
| O7 | Label 60+ critic crops (DESIGN 16.4) from M4.12's synthetic set plus hand picks; run `docla eval critic --live`; commit `rubric/calibration.yaml` | After M4 and O6 | M4 acceptance: critic precision gate (items at or above 0.8 become actionable) | Two calls per crop; my estimate $5 to $15 |
| O8 | "Slides complete" demo (gate G2): `docla write` on a real brief, look at the deck, the heal log and the ship gate | After O5, O7 | M4 acceptance | One deck, under the $5 budget |
| O9 | Merge the AGENTS.md change adding `registry.npmjs.org` to `Sandbox domains:` (protected file) | Before M5.08 | M5.08 to M5.13, M6d.05, M6d.06 | none |
| O10 | M5 hands-on: `docla serve`, edit a bullet, see render and finding in about 1 to 2 s; edit the `.md` outside and see it appear; merge M5.13 (CI, protected) | After M5 | M5 acceptance | none (fake or recorded calls) |
| O11 | Record cassettes for summariser, critic and the copyfit repair | After M4 and M6c | Replay tests for those roles | Small; my estimate under $5 |
| O12 | Look at the M6d acceptance report, its overlays and the parity rows; run a live `docla write` of a report | After M6 | M6 and v0.1 acceptance | One report, under the $5 budget |
| Later | S5 (brand claims on a real brand book) and S6 (Office fidelity on 5 templates) | Before M9 | M9 | S5 needs a real brand book; S6 needs LibreOffice |

---

## 6. Overnight run order, hand-back risks, and what needs the owner first

Throughput: 128 pieces of about an hour each is more than one night for one builder. Run in this order and stop at any
batch boundary; each boundary is a coherent state.

| Order | Batch | Unattended? | Needs first |
|---|---|---|---|
| 1 | B2 (26) | Yes | O0 (or accept defaults) |
| 2 | B3 (19) | Yes | B2 merged into the run base |
| 3 | M3 (16) | Yes (fakes only) | none paid; O4/O5 come after |
| 4 | M4 (12) | Yes (critic advisory) | none; O6/O7 come after |
| 5 | M5.01 to M5.07 (7) | Yes | none |
| 6 | M6a, M6b, M6c (35), M6d.01 to M6d.04, M6d.07 | Yes | none |
| 7 | M5.08 to M5.12, M6d.05, M6d.06 (7) | After O9 | O9 merged |
| 8 | M5.13 | No | owner merge (protected) |

M6d.07 depends on M6d.04, not on the web pieces, so the acceptance report builds unattended; the owner checks overlays by hand at O12.

Expected hand-back risks:

| Risk | Where | Mitigation in the specs |
|---|---|---|
| A new rule fires on a frozen clean text or blocks `geo.text-fits` | B3, M4.01 | B3 rule notes; each judge re-runs the clean texts |
| A component or chooser change breaks a pinned route or the four-manifest pin | B2 | Library folder; Q1 intent names; template D2 (stays) |
| Golden facts drift across platforms (macOS vs Linux shaping, pdfplumber versions) | B2.03 onward | 0.5 pt tolerance; fonts bundled; regenerate with the script, never hand-edit |
| `docs/schemas` out of date after a model change | B3.01, M4.07, M6a.02 | Regenerate in the same piece (rule 13) |
| Merge conflicts on `chooser.yaml`, `catalogue.py`, `cli.py`, `compose.py` | B2, B3, M3 | Serial dependency chains; `Shared files:` lines |
| Timing tests flaky on CI | M5.06, M6d.07 | Generous bounds (2 s); injected clocks |
| Typst missing in the builder sandbox | every render piece | Already required since M1.5; doctor reports it |
| The banned word "proof" in code, fixtures or `web/package-lock.json` | all, M5.08 | Rule in section 2; M5.08 judge checks the lockfile |
| SDK request shape for structured output wrong but invisible offline | M3.01 | O4 live smoke call before recording |
| Overflow clip hides words from pdfplumber, changing `geo.text-fits` lines | B2.06 | Judge re-checks the fail fixture's per-item lines |
| Critic cannot block anything before calibration | M4 | By design (11.4 rule 5); O6, O7 lift it |
| npm blocked | M5.08+ | Ordered after O9 |

---

## 7. Later roadmap (after v0.1)

| M | Pieces (outline) | About | Prerequisites |
|---|---|---|---|
| M7 Run isolation (19) | git wrapper with `--git-dir=.docla/git --work-tree=.` and cleared `GIT_*` env; run create, finish, prune; `docla merge-driver` from S7 code with `dropped.json` per run; server jobs run in worktrees; review API and screen (per-section accept, reject, retry); sequential merge of parallel runs; doctor checks git 2.20+ | 6 | M5, S7 (done); acceptance on a deck and a report |
| M8 Feedback and learning (12) | Feedback capture with snapshot; diagnoser (B.3); rule author (B.5); validation harness in a theme worktree (reproduces, gold silent, approved silent, conflicts, cost); impact preview; Teach card UI; theme branch merge with version bump; probation and stats; dismiss stats; re-heal; `docla theme revert`; `ruamel.yaml` for round-trip YAML edits | 12 | M6, M7; worked example 12.10 on a deck and a report |
| M9 Comprehensive ingestion (7) | Intake and manifest; PDF guideline segmenter and extractor with quote verification; PPTX/POTX and DOCX/DOTX structural reads; LibreOffice render; IDML; XLSX/CSV reference tables; fonts with licence flags; images into the asset library with tagging; Office safety checks; template-to-component mapping; comment import as seed feedback; questions UI; calibration critic (B.4); `ingest --update` | 18 | M2 to start, M8 to finish; S5, S6; LibreOffice on the machine |
| M10 Adaptation (20) | Signals log; miners (term swap, edit style, chooser, recipe, repair, false positive, graduation, component gap, exemplar curator); avoid notes (20.3a); FTS5 writer memory; autonomy dial with the monotone-strictness property test; component and check authoring in `ext/` branches; adaptation dashboard and weekly note | 9 | M8 |
| M11 Hardening and release | Docs site; example projects (deck and report); evals in CI (scheduled); installers; contributor guide; SECURITY.md and CODE_OF_CONDUCT.md; Playwright UI tests; packaged web app in the wheel; PyPI and npm publish; parity checklist fully green; tag v1.0 | 6 | All |

Nice to have, after v0.1 (DESIGN references):
- Charts beyond bar and column: line, donut, stacked, chart spec resolved from the data's shape, Python SVG option (9.6).
- Asset library: catalogue, tagging, FTS5 retrieval, closed-list selection, icons and the icon-list bullets variant,
  rights checks, `geo.logo` with a neutral logo (8.5, 10.5).
- `docla theme health`: rules by tier and origin, fire and false-positive rates, probation list (6.5).
- Adaptation dashboard and first-shot pass rate (20.9, 20.3a) ahead of the rest of M10.
- Contact sheets are in M4 because the critic's sequence items need them; if cut, the critic judges single pages only.
- Mode B repair with a `preview` tool (11.2), only if the heal eval shows equal success at lower cost.
- Incremental compile and swatch cache by content hash (9.5; S2 found them unnecessary for v1).
- Facts extraction in a process pool for long documents (S2 decision 2; 90 pages took 8.4 s serial).
- Deprecated-spelling alias table and composition schema migration (5.5, 15.3).
- Mutation-style CI step that corrupts good fixtures and expects the rule to fire (16.2).
- Inline edit on the page (13.3 phase 2); review bundle export (13.6).
- Migrate `statement` and `bullets` to `type-style` once their frozen sizes can move.
- DSL primitives `gap-between`, `align`, `ratio`, `count-per`; `src.capacity` minima.
- Windows support, RTL and CJK, an embeddings `Retriever` (21.1 decisions 13, 15, 18).

---

## 8. Open questions and contradictions, with the defaults the coordinator uses

| # | Question | Why it arises | Default used in this plan |
|---|---|---|---|
| Q1 | Intent name for timelines | Four frozen judges pin `timeline` as an unknown slides intent (and its fixture is the `source.intent-known` fail case) | Intent `chronology` for both formats; components `timeline` (slides) and `timeline-doc` |
| Q2 | Where new components live | test_m2_manifests pins the packaged folder to exactly four components; DESIGN 8.1 shows a folder per component | `src/docla/render/library/` flat, merged by `all_manifests()` (B2.02) |
| Q3 | Where new and richer doctypes live | test_m2_doctypes pins `load_doctypes()` to `pitch-deck` and `report` with the M2 outlines, not DESIGN 8.4's | Theme doctypes in `themes/neutral/doctypes/`, overriding by name through `load_doctypes(theme)` (M6d.01 to .03) |
| Q4 | `source.capacity` severity and minima | The frozen clean DOC has a callout with no items (minimum 1), and the text-fits fail fixture has 9 bullets: an error there would block `geo.text-fits` | Maxima only, severity warning. Minima stay with the chooser `when` clauses and `source.empty-section` |
| Q5 | When `source.outline-conforms` runs | The frozen clean texts do not conform to their doctypes' outlines, yet `check` must print `no findings` | Only with `docla check --outline` and in the macro loop's `validate` (B3.10, M4.10) |
| Q6 | Charts in v0.1 | The brief lists charts (9.6) as nice to have, but DESIGN 8.2 puts `chart` in the M2 slide set and M6d acceptance needs 6 charts | Bar and column only in v0.1 (B2.18, reused by M6b.05); other types after v0.1 |
| Q7 | Two-column reports | Neutral `doc.columns == 1` is pinned; M6d acceptance needs two columns | Front matter `columns: 2` (and doctype defaults) override the theme page (M6a.01) |
| Q8 | Source syntax for footnotes and cross-references | DESIGN 18.3 requires both but 5.2 defines no syntax | `[^: footnote text]` and `[see: <section-id>]` (M6a.06) |
| Q9 | Slide frames read from tokens? | DESIGN 6 says the engine holds no margin constant, but test_m2_theme_in_builds D3 requires a 120 pt theme margin to flag a clean bullets slide, so frames must not follow the theme | Fixed frames in `lib/frames.typ` matching the neutral 40 pt margins; revisit with theme-specific component overrides (6.1) |
| Q10 | Caption below the slides minimum | Neutral slides caption 14 pt is below `min_size` 18, and `geo.min-font` checks every word in a section | Raise caption to 18 (B2.01). Alternative: role-aware minimums in `geo.min-font` |
| Q11 | Pixel rules in M2 or M4 | DESIGN 10.5 lists `pix.*` in the catalogue (M2: "minus semantic") while 18.2 lists the pixel tier under M4 | M4.01, M4.02 |
| Q12 | Critic before calibration | DESIGN 11.4 rule 5 forces uncalibrated items to `info`; before O6 and O7 nothing is calibrated | Every rubric item advisory until `rubric/calibration.yaml` exists; the "slides complete" demo waits for O7 |
| Q13 | Does `docla build` write versions? | DESIGN 13.6 says every build is a version; frozen judges pin `build --out` outputs | `docla build` unchanged; versions written by the macro loop, `docla write`, `docla build --final` and server builds (M4.07, M4.11) |
| Q14 | Rule id prefixes | DESIGN uses `src.`; code uses `source.`; DESIGN 8.4 uses `deck.` | `source.`, `geo.`, `pix.`, `sem.`, `deck.` |
| Q15 | UI end-to-end tests | Playwright needs browser downloads from a domain outside the sandbox | vitest with jsdom in v0.1; Playwright in M11, or add its domain at O9 |
| Q16 | Model ids and prices | DESIGN 11.8 names `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-4-5`; S4 found Opus at effort medium enough for repair | Config defaults as DESIGN 11.8; owner confirms at O4 |
| Q17 | Logo and icons | No licensed logo or icon set ships with the neutral theme | `geo.logo`, icon lists and placements after v0.1 |
| Q18 | Volume against "one night" | 128 pieces at about an hour each | Run order in section 6; any batch boundary is a safe stop |
