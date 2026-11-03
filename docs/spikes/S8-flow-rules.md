# Spike S8: can document flow rules be measured?

Date: 2026-11-03. Typst 0.15.1, pdfplumber. Code: `docs/spikes/code/s8/`. Question (`DESIGN.md` 18.1): can widows and orphans,
keep-with-next, a near-empty last page and column balance be measured from the PDF plus marks reliably enough to drive repairs?
Done when: 12 seeded flow defects are detected with under 10% false positives.

## Method

- Two-column A4 pages (54 pt margins, 18 pt gutter, 10 pt text, 56 lines per full column).
- Calibration in Typst (`calib.typ`): a line box is 6.58 pt, the line pitch 13.08 pt, a 13 pt heading 8.385 pt, block spacing 12 pt.
  From these, a block can be placed so that exactly *k* of its lines fit above the column bottom.
- 26 scenes: 12 seeded defects (3 widows, 3 orphans, 2 headings stranded at a column foot, 2 near-empty last pages,
  2 unbalanced last pages) and 14 clean controls (splits of 2/4, 3/3 and 4/2, paragraphs that fit, headings with two body lines
  after them, full and balanced last pages).
- Every line carries tokens such as `p03l02a`, so **ground truth** comes from where each line actually landed in the PDF.
- The **detectors** see only line positions from the PDF and the paragraph start marks (`el`), never the tokens or the seeds.
  Lines are assigned to blocks by cut points in reading order, as in S1b.
- To make widows, orphans and stranded headings possible at all, the seeded document sets Typst's widow and orphan costs to 0% and
  uses plain blocks as headings. `defaults.py` repeats those placements with Typst's defaults.

## Results

| Rule | Seeded | Detected | False positives |
|---|---|---|---|
| Widow | 3 | 3 | 0 / 14 clean scenes |
| Orphan | 3 | 3 | 0 / 14 |
| Heading at the foot of a column | 2 | 2 | 0 / 14 |
| Near-empty last page (under 15% filled) | 2 | 2 | 0 / 6 last-page documents without it |
| Unbalanced last page (columns differ by more than a quarter column) | 2 | 2 | 0 / 6 last-page documents without it |
| **All** | **12** | **12** | **0** |

All 26 scenes came out exactly as seeded (ground truth matched the intent), so the comparison is against real layouts.

Each detection carries the amount a repair needs, and the amounts are exact:

| Case | Lines on the last page | Repair the detector proposes |
|---|---|---|
| Near-empty | 2 and 0 | cut about 2 lines before the page break |
| Near-empty | 5 and 0 | cut about 5 lines |
| Unbalanced | 56 and 3 | move about 26 lines from column 1 |
| Unbalanced | 56 and 8 | move about 24 lines from column 1 |

**With Typst's defaults, none of the 8 widow, orphan or heading placements produced a defect.** Widow and orphan costs at 100%
make Typst move a line rather than leave one alone, and a real `heading` is sticky: it moves with the paragraph after it.

## Decisions

1. Flow rules are measured from PDF lines plus block start marks. No new mark kinds are needed: reading-order cut points (S1b)
   identify the block of every line.
2. Widows, orphans and stranded headings are prevented by the theme, not repaired: keep Typst's widow and orphan costs at their
   defaults and use real (sticky) headings. The detectors stay as a check, because the costs are soft and can lose to other
   constraints.
3. Near-empty pages and unbalanced columns are repaired by copyfitting, as 11.7 proposes. The detectors give N: the lines on a
   near-empty page, or half the difference between the columns.

## Not covered

Justified and hyphenated text, mixed font sizes on a line (superscripts, inline maths), floats and footnotes on the same page,
tables, and real component output. Lines here are forced breaks of plain tokens. 14 clean controls is a small sample for a
false-positive rate. Column balancing by Typst itself was not tested. Re-run against the real component set at M6c.
