# Spike code (throw-away)

Scripts behind the notes in `docs/spikes/`. They are not part of the package and are not linted. Run them from this folder:

```
uv run --with pdfplumber --with pypdfium2 --with pillow python s1.py     # S1: slide marks against glyph positions
uv run --with pdfplumber --with pypdfium2 --with pillow python s1b.py    # S1b: flowing two-column A4 page
uv run --with pdfplumber --with pypdfium2 --with pillow python s2.py     # S2: timings
```

They need `typst` on the path (measured with 0.15.1). `gen.py` writes the fixtures: every word in a fixture is a token such as
`Z03q017`, so the true section of any word in the PDF is known. `s1b.py` writes overlay images to `out/`.

S7 uses the `docla` package, so run it from the repository root with the project environment:

```
uv run python docs/spikes/code/s7/s7.py     # S7: separate git dir, worktree runs, section-aware merge driver
```

It builds its test projects in a temporary folder.

S4 calls Claude. Its responses are recorded in `s4/cassettes/`, so a replay is free and needs no key:

```
uv run --with anthropic python docs/spikes/code/s4/s4.py            # arm A, replayed
uv run --with anthropic python docs/spikes/code/s4/s4.py --arm-b    # arm B, replayed
uv run --with anthropic python docs/spikes/code/s4/s4.py --mock     # plumbing check, no Claude
```

To record again (this spends money), set `DOCLA_RECORD=1` and provide a key in `ANTHROPIC_API_KEY` or in the macOS Keychain entry
`docla-anthropic-api-key`.

S8 needs only Typst and pdfplumber:

```
cd docs/spikes/code/s8 && uv run --with pdfplumber python s8.py         # seeded flow defects against detectors
cd docs/spikes/code/s8 && uv run --with pdfplumber python defaults.py   # the same placements with Typst's defaults
```

`calib.typ` measures the line height, line pitch and heading height the placements use.
