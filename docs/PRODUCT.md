# docla: the product for the first working version

Status: owner direction of 2026-11-13. This file says what docla does for the person using it. `DESIGN.md` says how the
engine works; where the two disagree, this file wins and `DESIGN.md` is updated when the affected piece is shaped.
`PLAN-v0.2.md` turns this file into pieces.

## 1. Two jobs

docla does two things.

1. **Learn a brand (setup).** A person drops in everything the brand has: brand books, templates, past decks and reports,
   logos, fonts, and notes on anything specific. docla turns that into the brand's ground rules: tokens, writing rules,
   checks, required elements and document types. Those rules then run on every generation, and docla fixes what fails
   before it shows anything to the person.
2. **Make reports.** For a brand that is set up, a person asks for a report, answers docla's questions, agrees an
   outline, and then works on the rendered report directly in the browser until it is right.

docla is single-user and runs locally. Several people working together is a later roadmap item, not part of this
version. Nothing here may make it harder to add later: new records that hold a person's input carry a person id.

## 2. Learning a brand

**Input.** One folder of materials per brand: guidelines (PDF), templates (PPTX, POTX, DOCX, DOTX), finished decks and
reports in the brand, logos, fonts with their licences, and free-text notes ("every report names its author",
"never use the word synergy").

**What docla produces**, each item citing where it came from (file, page and quote, or "measured over N examples"):

- **Tokens**: colours, fonts, type scale, margins, grid. Measured from the PDFs and templates where possible, never
  guessed from convention.
- **Rules**: writing rules and voice, layout rules, required elements (author name, date, disclaimer, logo position),
  each one a check with a severity and a repair route.
- **Document types**: from the brand's own examples (see section 4).
- **Questions**: every conflict, gap or doubt in the materials becomes a question for the person, shown with the page
  it came from. The person's answer becomes the rule.

The pipeline is `DESIGN.md` section 7 (stages S0 to S8), built in the order of `PLAN-v0.2.md`.

**Generic components.** docla's components are generic and read every visual value from the theme. Learning a brand
produces a theme; it never writes component code. A brand whose layout the generic set cannot express is a reason to
add a generic component (or a parameter) to docla, not a brand-specific one.

**Brand overview.** A page that shows the brand as docla understood it: tokens as swatches, every component rendered in
the brand, and the rules grouped by area with their source quote and whether they were extracted, measured, answered
by the person or learned later. Updating rules, syncing them to a backlog and learning from use are later work.

## 3. Where brands live, and how the engine changes

- A brand lives in `.brand/<slug>/` inside the docla checkout. `.brand/` is git-ignored by docla: brand material never
  reaches the docla repository. Each brand folder is its own local git repository.
- A change to a brand (tokens, rules, a document type, answers to questions) is made on a branch of the brand
  repository and merged with a change record: what changed, why, the evidence, and rendered pages before and after.
  The record is the brand's history and its review step.
- A change to the generic engine (a new component, a new rule kind, a new doctype field) is a branch of docla and a pull
  request into `main`, with the same kind of record, merged by the owner.
- Reports for a brand live in `.brand/<slug>/reports/<report>/`, one docla project per report.

The final layout of brand storage is decided later; this is the layout for local testing.

## 4. Document types

A document type says how one kind of report is built: its outline (required and repeating parts), boilerplate and
fixed text, default audience and length, required fields, the checks that apply, and the questions to ask. Types belong
to a brand (`.brand/<slug>/theme/doctypes/`); docla's packaged types are the fallback.

A person makes a type in one of two ways:

- **From an example**: docla reads a finished report and proposes the type; the person confirms it.
- **By conversation**: the person describes it and docla drafts it.

Either way the type arrives as a brand change with a record (section 3).

## 5. Making a report

1. **Request.** The person picks the brand, drops in data (spreadsheets, PDFs, notes) and writes what they need, for
   example "a sales report for last quarter for the board, focusing on the initiatives and profitability". A document
   type may be chosen or left for docla to infer.
2. **Intake interview.** docla first shows a read-back of what it already understood from the request, the data and the
   type. It then asks in rounds of two to four numbered questions, each with a recommended answer drawn from the data
   and worded so that "yes" accepts it. Facts are docla's job: it never asks what the data or the type can answer, and
   shows each inference with its evidence for confirmation instead. Judgements are the person's: who reads it and what
   they must decide, the key message, the ask, which findings are the story and why they happened, what must not be
   said, and tone. Every question can be skipped. There are at most three rounds; anything still open becomes a flagged
   assumption in the outline. The result is a **brief** that records, for each field, whether it was confirmed,
   inferred, defaulted or skipped.
3. **Outline.** docla proposes an outline from the brief with its uncertainties resolved. The person comments on it;
   docla answers questions and proposes changes, which the person accepts or rejects. Drafting starts when the person
   says so.
4. **Generation.** docla drafts, renders, checks against the brand's rules and fixes, then shows the result.
5. **Working on the rendered report: the core of the product.** The browser shows the report exactly as the output
   will be (the rendered PDF pages, not an approximation). The person:
   - edits text directly on the page: a click on a title, bullet or paragraph edits it in place, and the page
     re-renders within about one to two seconds;
   - comments on one component (a chart, a slide, a paragraph) or on the whole report.
6. **Apply.** When the person applies their changes, docla:
   1. keeps every direct edit as the person's own; regeneration never rewrites it;
   2. reads each comment as a question, a change or a note on wording;
   3. asks its clarifying questions in one round, in the intake format ("Add a chart for the margin drop?", "Cut slides
      7 and 8?");
   4. regenerates, checks and fixes, and shows the new version with what changed.
7. **Export.** The output is a PDF. Every export is an immutable version.

Choosing a layout from previews, chart options and other pickers are later enhancements of this core.

## 6. Numbers and sources

- **No invented numbers.** Numbers come from the person's data. A deterministic check refuses any number in the
  report that does not appear in the data, and checks that the cited source contains the number, not only that the
  citation exists.
- **Data first.** Spreadsheets are read into facts with their sheet and cell; charts, key figures and tables draw
  from that data, so they cannot drift from it. A chart is resolved once into a spec, and the renderer only draws it.
- **Source links.** Each quoted number carries a small link; hovering shows the file, the place (sheet and cell, or
  page) and the value.
- **Gaps** are not shown to the person as a general concept. Missing facts are settled in the intake interview, and a
  brand's required elements (author name, date) are checks and intake questions. Internally, the engine still refuses
  to invent a value.

## 7. Formats

The first version makes **decks** (16:9 slides), output as PDF. **Documents** (A4 reports) follow straight after, and
every model, route and screen built now must already carry the format and work for documents without being redesigned:
the brief, the outline, editing, comments and sources are the same for both. Word and PowerPoint output are later, as
extra output targets drawn from the same component spec (one spec per component, never a second component library).

## 8. What the person sees and does not see

The person sees reports, the brand, questions, comments and changes. The engine's own views (findings with rule ids,
the repair replay, version comparison, cost) stay available behind a developer mode. The interface uses the words of
the `docla-vision` prototype; `CONTEXT.md` maps each code term to its interface word. The prototype (V11) is the
reference for the interface's look, copy and behaviour, within the scope of this file.
