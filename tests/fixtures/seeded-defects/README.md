# Seeded-defect fixtures

One folder per rule: `<rule-id>/fail/` holds a fixture that breaks the rule, and
`<rule-id>/pass/` holds one that satisfies it. A rule folder missing either side
fails `tests/test_fixture_pairs.py`.
