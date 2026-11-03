# Spikes S1 and S1b: section regions and element boxes from Typst marks

Date: 2026-11-03. Typst 0.15.1, macOS 15 on Apple silicon. Code: `docs/spikes/code/`. Question (`DESIGN.md` 18.1): can `metadata` marks give
section regions and element boxes accurate to about 1 pt, for a fixed slide frame (S1) and for a flowing two-column A4 page (S1b)?

## S1, slides: yes, exact

Three 960 x 540 pt slides, each a section with a title and a body, read with `typst eval` and compared with glyph positions from the PDF (pdfplumber).

| Measure | Result |
|---|---|
| Left edge of mark against first glyph | 0.00 pt |
| Width of a one-line title against the glyphs | 0.00 pt |
| First baseline against mark `y` (inline text) | 0.00 pt |
| Last baseline against mark `y + h` (block) | 0.00 pt |

Two things the design did not say:

1. `here().position()` returns the **baseline** for inline content and the **top edge** for a block. A component helper must wrap its body in a `block` so every mark means one thing (`el` in `code/lib/marks.typ` does).
2. The layout box runs from cap height to baseline (Typst's default text edges), while pdfplumber reports the font's ascender to descender. Checks must compare like with like: use the marks for layout boxes and baselines for text. Setting `top-edge: "ascender"` and `bottom-edge: "descender"` in the theme would make the two agree.

## S1b, flowing documents: yes, with marks as cut points

A 4-page, two-column A4 report with 10 sections, three figure floats, one float spanning both columns, a page break, and a 40-row table that breaks across a page. It holds 1,982 tokens, each tagged with its true section.

| Method | Words in the right section |
|---|---|
| Marks: section start marks as cut points in reading order, plus an `el` mark inside each float | 1982 / 1982 |
| Title search only (no marks): section starts found from the heading words | 1968 / 1982 (all 14 errors are floats: 6 of 18 figure words, 0 of 8 spanning-float words) |
| Marks only, boxes derived from start, end and the column geometry | 1968 / 1982 recall, and 14 words inside the boxes belong to other sections |

- A section's end mark is identical to the next section's start mark, so start marks alone are enough.
- A mark inside a float body reports the float's **final placed position** (the top of the next column, or the top of the next page), exact to the decimal, and every caption lies inside its box.
- Table rows: 40 of 40 row marks sit on the same page as their words, `x` is exact, and the baseline is a constant 6.58 pt below the mark (cell inset plus ascent).
- Overlay images were checked by eye on one page (page 2): the spanning float, a section continuing across columns, and the table breaking to the next page all line up.
- A box built from the union of word boxes covers the text, not the frame: it stops short of the table's right border. Frames need their own `el` marks.

## Decisions

1. Marks are used for slides and documents. The title-search fallback is not needed, but it is a sound degraded mode for flow text (100% on 1,800 flow words).
2. A document section is described by its start mark (the cut point), its float marks, and the PDF words between cut points. Region boxes come from the assigned words; frames from `el` marks.
3. Use `typst eval 'query(<doclo-mark>).map(it => it.value)' --in <file>`, not `typst query`: `query` is deprecated in 0.15.1 and prints a warning. The JSON is identical.
4. `el` always wraps its body in a `block`.

## Not covered

Footnotes, hyphenation and justification, images split across columns, a table that spans both columns, and right-to-left text. The fixtures use unbreakable tokens. Re-run S1b on a real component set at M6a.
