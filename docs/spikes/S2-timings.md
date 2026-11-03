# Spike S2: timings

Date: 2026-11-03. Typst 0.15.1, macOS 15, Apple silicon. Python 3.10.12 (what `uv run --with` picked; re-measure on 3.12 in M1). Median of three runs; code in `docs/spikes/code/s2.py`.
The fixtures are plain text with a few rectangles and no images or custom fonts, so compile times are a lower bound.

| Case | Pages | Compile | `typst eval` marks | Raster 1x | Raster 2x | pdfplumber chars | Words and shapes |
|---|---|---|---|---|---|---|---|
| 1 slide (swatch) | 1 | 0.02 s | 0.01 s | 0.00 s | 0.00 s | 0.02 s | 0.01 s |
| 20-slide deck | 20 | 0.03 s | 0.02 s | 0.02 s | 0.07 s | 0.26 s | 0.27 s |
| 25-slide deck | 25 | 0.03 s | 0.02 s | 0.02 s | 0.08 s | 0.34 s | 0.35 s |
| Report, 208 marks | 18 | 0.04 s | 0.04 s | 0.04 s | 0.09 s | 1.41 s | 1.55 s |
| Report, 874 marks | 90 | 0.15 s | 0.13 s | 0.16 s | 0.43 s | 7.74 s | 8.40 s |

The 18-page report has 74,879 characters; the 90-page report has 397,875.

## Against the targets in `DESIGN.md` 9.5

| Target | Result |
|---|---|
| Swatch, one section, under 1 s | 0.02 s plus 0.01 s: met by a wide margin |
| Full draft render, 25 slides or 20 pages, under 5 s | 0.03 s and 0.04 s: met |
| Facts extraction under 2 s | 0.27 s for 20 slides and 1.55 s for 18 dense pages: met. 8.4 s for 90 pages: not met without a pool |
| Look (raster, facts, deterministic checks) under 8 s | about 1.7 s for 18 pages: met |

## Determinism

Compiling every case twice with `SOURCE_DATE_EPOCH=0` and `--ignore-system-fonts` gave **byte-identical PDFs** in all five cases.

## Decisions

1. Typst compile and mark reading are negligible. Incremental compile and swatch caching are not needed for v1; they stay on the list in 9.5.
2. pdfplumber extraction is the only real cost, at roughly 50,000 characters a second. Cache facts by PDF hash and extract pages in a process pool from M1.
3. The 100-page document is within reach (under 10 s serial) so no fixed size limit is needed, in line with decision 16.
4. Pin Typst at 0.15.1.
