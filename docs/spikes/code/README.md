# Spike code (throw-away)

Scripts behind the notes in `docs/spikes/`. They are not part of the package and are not linted. Run them from this folder:

```
uv run --with pdfplumber --with pypdfium2 --with pillow python s1.py     # S1: slide marks against glyph positions
uv run --with pdfplumber --with pypdfium2 --with pillow python s1b.py    # S1b: flowing two-column A4 page
uv run --with pdfplumber --with pypdfium2 --with pillow python s2.py     # S2: timings
```

They need `typst` on the path (measured with 0.15.1). `gen.py` writes the fixtures: every word in a fixture is a token such as
`Z03q017`, so the true section of any word in the PDF is known. `s1b.py` writes overlay images to `out/`.
