# docla v0.2 plan: the first working version

Status: owner direction of 2026-11-13 (`PRODUCT.md`). This plan replaces the order of `PLAN-v0.1.md` after M5's server
side. Everything `PLAN-v0.1.md` built (B2 to M5.07) stays; its M5 web pieces (#301 to #306) and M6 are re-planned here.

## 1. Definition of done

The first working version is done when the owner can do all of this locally, on a real brand:

1. Ingest a brand from its own materials and see the brand overview, with every token and rule citing its source
   (owner step V-A).
2. Compare that ingestion with the brand book and find most tokens and hard rules right (owner step V-A).
3. Ask for a board sales report deck from a spreadsheet, answer the intake interview, and agree an outline (V-B).
4. Edit text on the rendered deck in the browser and see the change in about 1 to 2 s (V-C).
5. Comment on a slide and on the whole deck, apply, answer docla's questions, and get a new version that keeps every
   direct edit (V-C).
6. Hover a number and see where it came from; find no number that is not in the data (V-C).
7. Build the same brief as an A4 document with the current document components, with no change to the brief, outline,
   editing or source models (V-D).

## 2. Global rules

`PLAN-v0.1.md` section 3 applies, with these changes:

- **Network**: builders reach pypi.org, files.pythonhosted.org and registry.npmjs.org (O9 is merged).
- **New dependencies planned** (each through `scripts/licence_report.py`): `openpyxl` (MIT, A.01), `python-pptx` (MIT,
  B.05), `python-docx` (MIT, B.05), `fonttools` (MIT, B.03), npm `@types/react` and `@types/react-dom` (MIT, E.01).
- **Test brands.** Judges never use real brand material. A judge that needs brand material builds a small synthetic
  pack in the test: a guidelines PDF compiled with Typst from committed source, a template written with `python-pptx`,
  fonts from the neutral theme. Real brands are used only in owner steps, from `.brand/` (git-ignored).
- **Measured hard rules**: a value measured from a template the brand supplied may make a hard rule; `DESIGN.md`'s ban on
  hard measured rules is narrowed to values measured from examples (DESIGN is updated with B.08).
- **Brand storage**: `.brand/<slug>/` (git-ignored), each a local git repository (`PRODUCT.md` section 3).
- **Every new model carries `format`** where the thing it describes differs between slides and documents, and every
  new route and screen takes a document of either format (`PRODUCT.md` section 7).
- **Interface pieces** cite the `docla-vision` V11 prototype for look, copy and behaviour by file, and use the
  interface words of `CONTEXT.md`. A judge checks structure and behaviour; the owner checks the look (owner steps).

## 3. Tracks

Five tracks. Python tracks (A to D) and the web track (E) run as separate chains. Keys are `<track>.<nn>`. Sizes and
scope are first estimates; each track is shaped into issues when it starts.

### A. Data and sources (8)

| Key | Piece | Builds on | Dep |
|---|---|---|---|
| A.01 | Read xlsx and csv into facts: one fact per cell or row with `sheet!cell` locators, typed values (number, percent, currency, date) | `sources.py`, `agents/gatherer.py` `Fact` | none |
| A.02 | Structured numeric facts: `Fact.value` and `Fact.unit`; every number the writer may use resolves to a fact id | `loop/guards.py` `FactGuard` | A.01 |
| A.03 | Rule `source.number-in-source`: the cited source contains the number, within its rounding | `checks/catalogue.py` | A.02 |
| A.04 | Rule `data.values-visible`: every value a section declares appears on the rendered page | layout facts | A.02 |
| A.05 | Chart spec resolved once from a `data` block (type with reason, scale, labels, colour roles); the chart component only draws it (#178) | `render/library/chart.typ` | A.02 |
| A.06 | Source marks: components emit a mark per cited number with its fact id and box | `render/marks.py` | A.02 |
| A.07 | Route `GET /api/docs/{doc}/facts/{id}`: file, place, value and quoted text | `server/` | A.06 |
| A.08 | Twin table for every chart (same formatted numbers), for documents and accessibility | A.05 | A.05 |

### B. Brand setup (23)

`DESIGN.md` section 7, cut to what the first version needs, with the lessons of the owner's own brand build
(`PRODUCT.md` section 2): fonts first, value labels, rule or illustration, the brand's gaps, a departures register,
and the correction loop (B.12, B.23) as the core of setup.

| Key | Piece | Builds on | Dep |
|---|---|---|---|
| B.01 | Brand workspace: `docla brand init <slug>` makes `.brand/<slug>/` (materials, theme, reports) as a local git repository; `.brand/` git-ignored | `theme/loader.py` | none |
| B.02 | Change record: a brand change is a branch plus a merge whose record holds what, why, evidence and before/after renders; `docla brand log` | B.01 | B.01 |
| B.03 | Intake (S0): manifest with hashes, types, page counts; font licence gate with `fonttools` | B.01 | B.01 |
| B.04 | Parse PDFs (S1): page index with text, fonts, colours, images and page PNGs | `facts/pdf.py`, `facts/raster.py` | B.03 |
| B.05 | Parse PPTX and DOCX templates: theme colours, fonts, layouts, placeholders, styles (`TemplateFacts`); a template value that disagrees with the guidelines is recorded as drift | DESIGN 7.8 | B.03 |
| B.06 | Segment (S2): pages to topics, small model, cassette-tested | `agents/client.py` | B.04 |
| B.07 | Extract claims (S3) with code-verified quotes; a claim without a found quote is dropped | B.06 | B.06 |
| B.08 | Measure examples and the guidelines' own layout pages (S4) and reconcile with claims: agreements, conflicts as questions, regularities as proposed rules | `facts/`, B.07 | B.07 |
| B.09 | Synthesise (S5): `tokens.yaml`, rule files with check specs, voice terminology, required elements | `theme/` | B.08 |
| B.10 | Questions (S6): model, storage, answers become rules; API routes | `server/` | B.09 |
| B.11 | Specimen deck per doctype rendered with the draft theme, and a specimen sheet | `render/`, `store/` | B.09 |
| B.12 | Calibration loop (S7): critic lists what differs between specimen pages and the brand's pages (guideline layout pages and examples); at most 4 rounds, stop if differences grow | `agents/critic.py` | B.11, B.20 |
| B.13 | Brand overview data: route for tokens, components rendered in the brand, rules with provenance, origin, value label and departures | B.09 | B.10, B.16, B.21 |
| B.14 | Server uses the theme of each document's brand (`front.theme`), not the neutral theme | `server/app.py` | B.01 |
| B.15 | Font check: each supplied font's family and weight read from its name table and matched to the brand's named typefaces; licence recorded; a missing font is a question, never a silent fallback | B.03, `fonttools` | B.03 |
| B.16 | Value labels: Measured, Derived, Inferred or Answered on every token and rule, checked by the theme loader | `theme/loader.py`, B.09 | B.09 |
| B.17 | The brand's gaps and identity check: what the brand does not provide, the guidelines' version and date, and a question about earlier identities | B.03 | B.03 |
| B.18 | Rule or illustration: claims taken only from an illustration are marked illustrative and become questions | B.07 | B.07 |
| B.19 | Vector measurement: rules, strokes and fills from PDF vector data; the unit grid per format, width and height kept separate | B.04, `facts/pdf.py` | B.04 |
| B.20 | Examples to roles: the person maps example slides and pages to component roles; each mapping cited | B.04, B.05 | B.05 |
| B.21 | Departures register: values that depart from the brand's sources, with reason; recorded only on the person's approval | B.02 | B.02 |
| B.22 | Signature graphic (one per brand in this version): traced from the brand's examples into data, drawn by a generic generator, validated against the traced set | B.19, `render/library/` | B.19 |
| B.23 | Correction data: each difference the person confirms becomes a brand change with before and after renders; routes for the side-by-side and the differences list | B.12, B.02 | B.12 |

### C. Document types (5)

| Key | Piece | Builds on | Dep |
|---|---|---|---|
| C.01 | Brand doctypes: loaded from `.brand/<slug>/theme/doctypes/`, packaged types as fallback | `doctypes/` | B.01 |
| C.02 | Doctype fields: the sequence of layouts and the layouts allowed for each part, fixed text and boilerplate parts, required fields, default audience and length, fill modes (`facts`, `summary` written last, `fixed`) | C.01 | C.01 |
| C.03 | Doctype from an example: a finished report becomes a proposed type (using the example-to-role map), as a brand change | B.04, B.02, B.20 | C.02 |
| C.04 | Board report doctype (deck), with its document twin outline | C.02 | C.02 |
| C.05 | Doctype by conversation, using the intake engine | D.03 | D.03, C.02 |

### D. Intake and outline (8)

| Key | Piece | Builds on | Dep |
|---|---|---|---|
| D.01 | Brief model: audience and decision, key message, ask, scope, findings, metrics, comparisons, exclusions, tone, length, required elements, and per-field provenance (confirmed, inferred, defaulted, skipped) | `model/` | none |
| D.02 | Data profiler: inferred brief fields with evidence from facts and the doctype | A.02, D.01 | D.01, A.01 |
| D.03 | Interview engine: read-back, rounds of 2 to 4 questions from the frontier, recommended answers, skip, three-round ceiling; Claude role `interviewer`, cassette-tested | `agents/` | D.02 |
| D.04 | Intake routes: start, answer a round, get the brief; state stored in the report | `server/` | D.03 |
| D.05 | Planner from the brief: outline with every section tied to brief fields and facts | `agents/planner.py` | D.01 |
| D.06 | Outline feedback: a comment on the outline gives an answer or a proposed change to accept or reject | D.05 | D.05 |
| D.07 | Draft over HTTP: the server runs what `docla write --approve` does, with progress events | `write.py`, `server/jobs.py` | D.05 |
| D.08 | Report creation route: new report in a brand, upload data files, request text | `server/` | B.01 |

### E. The editor (15)

Engine pieces (E.02 to E.06) are Python; the rest are web. The web pieces replace #301 to #305.

| Key | Piece | Builds on | Dep |
|---|---|---|---|
| E.01 | Web scaffold: #301 as shaped, plus `@types/react` and `@types/react-dom`, strict types, V11 tokens in `web/src/styles/tokens.css` | #301 | none |
| E.02 | Field marks: every element mark names the field it draws (`title`, `items[1].body`, `paragraphs[0]`) | `render/marks.py`, components | none |
| E.03 | Comment store: comments on a report or a section, with person id, thread and state | `model/`, `store/` | none |
| E.04 | Apply pipeline: direct edits kept as the person's; comments sorted into question, change or wording; clarifying questions as one round; proposals; regenerate | `loop/`, D.03 | E.03, D.03 |
| E.05 | Version PDF download route and "what changed" between two versions (sections edited, regenerated, added, removed) | `server/versions.py` | none |
| E.06 | Developer mode data: findings and repair history routes stay; flagged as developer views | `server/` | none |
| E.07 | App shell: brands, reports, new report (upload and request) | E.01 | E.01, D.08 |
| E.08 | Intake screen: read-back, question rounds, brief | E.07 | E.07, D.04 |
| E.09 | Outline screen with comments and proposals | E.08 | E.08, D.06 |
| E.10 | Report view: rendered pages, slide list, select an element (from field marks) | E.07 | E.07, E.02 |
| E.11 | Edit in place: an editable overlay on the selected element, debounced save, fresh page within about 1 to 2 s | E.10 | E.10 |
| E.12 | Comments on an element, a slide or the report | E.10 | E.11, E.03 |
| E.13 | Apply screen: questions, proposals to accept, new version and what changed; PDF export | E.12 | E.12, E.04, E.05 |
| E.14 | Source hover on numbers | E.10 | E.10, A.07 |
| E.15 | Brand overview, brand questions and the side-by-side correction screen; developer mode views | E.07 | E.07, B.13, B.10, B.23 |

#306 (the CI web job, owner merge) is kept and lands after E.01.

### F. Documents aligned

Not a build track yet. Every piece above states, in its Contract, how it handles a `doc` format document, or why it
does not apply. Owner step V-D checks it. `PLAN-v0.1.md` M6 is re-cut after V-C, with the brief, outline, editor and
source models of this plan as fixed inputs.

## 4. Order

1. Phase 0 (this plan): `PRODUCT.md`, `PLAN-v0.2.md`, the `CONTEXT.md` glossary, `.brand/` ignored. Close #302 to #305
   and fold #178 to #185 into the tracks.
2. Install the AI Loop Kit release that includes kit #528, before the web chain.
3. First wave, in parallel: B.01, B.02, B.03, B.14, B.15, B.17 (brand workspace and intake); A.01, A.02 (data); D.01 (brief); E.01, E.02, E.03, E.05
   (editor foundations).
4. Second wave: the rest of A and B; C.01, C.02, C.04; D.02 to D.08.
5. Third wave: E.04, E.06 to E.15, C.03, C.05.

Each wave is one or more loop chains with the dashboard running. Pieces in a chain that edit the same shared file
depend on the previous one (`PLAN-v0.1.md` section 3 rule 16).

## 5. Owner steps

| Step | What the owner does | After |
|---|---|---|
| V-0 | Review and merge the Phase 0 pull request | Phase 0 |
| V-A | Ingest two real brands from `.brand/`; correct each side by side against its brand book until accepted; compare tokens and hard rules with the brand book; answer the brand questions. Test brands: the WWF, Munich Re and TU Delft public kits (local only); experiments: colour roles, typography by role, grid from masters, voice, chart styling, template against guidelines, and a blind run from examples only | B.13, E.15 |
| V-B | Make a board sales report deck from a spreadsheet through the intake screen; agree the outline | E.09 |
| V-C | Edit, comment and apply on the rendered deck; check source hovers and numbers | E.14 |
| V-D | Build the same brief as an A4 document | V-C |
| V-E | Record the cassettes for the model roles added here (interviewer, segment, extract, calibrate, apply) | before V-A to V-C |
