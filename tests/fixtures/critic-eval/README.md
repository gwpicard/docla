# Critic evaluation crops

These labelled crops exercise focal point, repetition and balance. Clean examples are labelled pass and synthetic mutations fail. The slide swatches and document pages were rendered with the neutral theme and its OFL fonts, whose licences are recorded in `src/docla/themes/neutral/fonts/LICENSES.txt`. Contact sheets and spreads use the standard sheet helpers.

To add cases, place PNG crops in `crops/` and add unique IDs, crop paths, rubric IDs and person-reviewed pass or fail verdicts to `labels.yaml`. `scripts/mutate_crops.py IN_DIR OUT_DIR` generates candidate failures for review. Run `docla eval critic --cases tests/fixtures/critic-eval --out evals/CRITIC.md`; add `--calibration FILE` to save offline calibration, or opt into a live run with `DOCLA_LIVE=1` and `--live`.
