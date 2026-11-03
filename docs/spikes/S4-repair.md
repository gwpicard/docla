# Spike S4: does patch-based repair converge?

Date: 2026-11-03. Claude Opus 5.5 (`claude-opus-5-5`), effort `medium`, structured output, Typst 0.15.1. Code and recorded responses:
`docs/spikes/code/s4/`. Question (`DESIGN.md` 18.1): does patch-based repair converge on overflow and long-title defects in at most
3 attempts without losing facts? 20 seeded sections; attempts and fact loss reported.

## Set-up

- 20 seeded slide sections, each with a measured defect at the start: 8 titles that need two or three lines in a one-line box,
  8 item lists that overflow their 560 x 260 pt box (by 10.8 to 81.5 pt), and 4 sections with both. 252 facts in all
  (numbers, dates, names), with citations on every item.
- Each attempt renders the section alone (a swatch), reads `fit-box` marks, and sends the findings to Claude with the repair prompt
  from `DESIGN.md` B.2 (text only, no images). Claude returns the whole title and items; they go through the real `apply_patch`
  from M1 as a `set_fields` patch, with the fact guard of 11.5 as its hook. A candidate is kept only if the overflow goes down.
- Facts are counted per field. Citations are checked separately, and every lost or invented token is listed.

## Results

| | Arm A: box-level findings | Arm B: findings name the wrapping items |
|---|---|---|
| Cleared in at most 3 attempts | **16 / 20** | **20 / 20** |
| Long titles | 8 / 8, all in 1 attempt | 8 / 8, all in 1 attempt |
| Overflowing item lists | 6 / 8 | 8 / 8 (7 in 1 attempt, 1 in 2) |
| Both | 2 / 4 | 4 / 4 (3 in 1 attempt, 1 in 2) |
| Facts kept | 248 / 252 (98.4%) | 248 / 252 (98.4%) |
| Citations lost, items deleted | 0, 0 | 0, 0 |
| Patches rejected by the fact guard | 0 | 1 (a false alarm, below) |
| Tokens (in, out) and cost | 36,238, 32,738: **$0.80** | 29,889, 23,804: **$0.60** |

The only difference between the arms is the finding text. Arm A says "the item list overflows its box by 10.8 pt". Arm B adds the
measured lines per item and roughly how many characters would bring each wrapped item back to one line.

## What the spike showed

1. **Repair converges when the finding says where to cut.** In arm A, all four failures were 6-item lists. The first attempt took
   each from 81.5 pt over to 10.8 pt over; the next two attempts cut 26 characters spread over four items and the measured height
   did not move (270.8 pt before and after). Height only changes in whole lines, and no single item lost a line. Arm B, which names
   the items that wrap and the cut that frees a line, cleared all of them, at lower cost.
2. **Facts in a title are the ones that get lost.** All 4 lost facts (in both arms) were in long titles whose facts appear nowhere
   else: "North Sea", "14", "Asset Integrity", "12 December". 98.4% is just under the M3 target of 99%. Nothing in the items was lost.
3. **The fact guard in 11.5 needs four changes.** Found with a mock run before any paid call, and in arm B:
   - Tokenise **per field**. Joining title, head and body let the entity pattern invent names across fields ("Pilot" + "Maria Jensen").
   - Check **citations separately**. Locators such as `00:41`, `p.4` and `row 212` are not facts.
   - **Normalise number words.** Arm B's one rejection was "month one, month six" rewritten as "month 1, month 6".
   - The guard catches **invented** facts only. A mock run that deleted 63% of the facts passed it. The loop needs a separate
     kept-facts check.

## Decisions

1. Overflow findings for lists and paragraphs report **per element**: lines used, and how many characters free one line. This goes
   into the geometry sensors at M1 and M3, and into the B.2 prompt.
2. The fact guard is tokenised per field, checks citations separately, normalises number words, and is paired with a kept-facts
   check that turns a lost fact into a finding.
3. The repair prompt tells the writer that a fact a title cannot hold may move into an item, not be dropped. Test this at M3; it is
   the remaining gap to 99%.
4. Claude Opus 5.5 at effort `medium` is enough for repair at about 3 cents per attempt. Images (B.2's "IMAGES") were not needed for
   these two defect types.

## Not covered

Defects other than overflow and long titles, documents (flowing pages), images in the prompt, best-of-N, other models or efforts,
and repeat runs (each arm ran once, so these are single samples; the recorded responses make the numbers reproducible, not certain).
