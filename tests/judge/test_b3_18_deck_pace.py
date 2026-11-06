# Intent: detect repeated slide components across sections with a macro-level warning.
import dataclasses
import importlib.util
import runpy
from pathlib import Path

import pytest

try:
    from docla import cli
    from docla.checks import catalogue, engine, source
    from docla.model import Document
    from docla.render import compose
except ImportError as error:
    if error.name != "docla" and not str(error.name).startswith("docla."):
        raise
    if importlib.util.find_spec(error.name) is not None:
        raise
    cli = catalogue = engine = source = Document = compose = None

ROOT = Path(__file__).resolve().parents[2]
SEEDED = ROOT / "tests/fixtures/seeded-defects/deck.no-component-three-running"
RULE_ID = "deck.no-component-three-running"


def _rule():
    assert catalogue is not None and hasattr(catalogue, "all_rules"), "catalogue.all_rules must exist"
    rules = [rule for rule in catalogue.all_rules() if rule.id == RULE_ID]
    assert len(rules) == 1, "the deck sequence rule must exist exactly once"
    return rules[0]


def _context(components=None):
    assert engine is not None and hasattr(engine, "CheckContext") and hasattr(engine, "run_checks")
    assert "composition" in {field.name for field in dataclasses.fields(engine.CheckContext)}
    assert compose is not None and hasattr(compose, "Composition") and hasattr(compose, "ComposedSection")
    doc = Document(front={}, format="slides", sections=[])
    composition = None
    if components is not None:
        composition = compose.Composition(
            format="slides",
            sections=[
                compose.ComposedSection(id=f"s{i}", component=component, props={})
                for i, component in enumerate(components, 1)
            ],
        )
    return engine.CheckContext(doc=doc, composition=composition)


def _run_cli(path, out_dir, capsys):
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    try:
        code = cli.main(["check", str(path), "--out", str(out_dir)])
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_catalogue_rule_metadata_and_order():
    rule = _rule()
    rules = catalogue.all_rules()
    ids = [item.id for item in rules]
    assert ids.count(RULE_ID) == 1
    assert "deck.pace-every" not in ids
    assert [item.id for item in catalogue.m1_rules()] == [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
    ]
    assert [item.id for item in source.RULES] == ["source.citations-resolve", "source.empty-section"]
    assert ids.index(RULE_ID) > max(ids.index(item.id) for item in [*catalogue.m1_rules(), *source.M2_RULES])
    assert (rule.title, rule.origin, rule.strength, rule.status) == (
        "No component draws three slides in a row",
        "manual",
        "soft",
        "active",
    )
    assert (rule.severity, rule.tier, rule.remedy.class_, rule.scope.format) == (
        "warning",
        "source",
        "restructure",
        "slides",
    )
    assert getattr(rule, "loop", None) == "macro"
    assert rule.check == {"kind": "sequence", "over": "sections", "window": 3, "forbid_repeat": "component"}


def test_D2_maximal_runs_and_missing_composition():
    rule = _rule()
    cases = [
        (["bullets", "bullets", "bullets"], [("s1", "bullets", 3, ["s1", "s2", "s3"])]),
        (["bullets", "bullets", "bullets", "bullets", "statement"], [("s1", "bullets", 4, ["s1", "s2", "s3", "s4"])]),
        (["bullets", "bullets", "statement", "bullets", "bullets"], []),
        (
            ["bullets"] * 3 + ["statement"] * 3,
            [("s1", "bullets", 3, ["s1", "s2", "s3"]), ("s4", "statement", 3, ["s4", "s5", "s6"])],
        ),
        (None, []),
    ]
    for components, expected in cases:
        findings = engine.run_checks([rule], _context(components))
        assert [
            (f.section_id, f.measured["component"], f.measured["run"], f.measured["sections"]) for f in findings
        ] == expected
        for finding in findings:
            assert finding.rule_id == RULE_ID
            assert finding.measured["component"] in finding.message
            assert str(finding.measured["run"]) in finding.message


@pytest.mark.parametrize(("key", "value"), [("over", "pages"), ("forbid_repeat", "intent")])
def test_D3_unsupported_parameters_name_the_value(key, value):
    rule = _rule()
    changed = rule.model_copy(update={"check": {**rule.check, key: value}})
    with pytest.raises(ValueError, match=value):
        engine.run_checks([changed], _context(["bullets"] * 3))


def test_D4_seeded_working_files(tmp_path, capsys):
    for case in ("fail", "pass"):
        path = SEEDED / case / "doc.md"
        assert path.is_file(), f"missing seeded {case} working file"
        code, out, err = _run_cli(path, tmp_path / case, capsys)
        assert code == 0, (out, err)
        deck_lines = [line for line in out.splitlines() if " deck." in line]
        if case == "fail":
            assert len(deck_lines) == 1 and deck_lines[0].startswith("warning deck.no-component-three-running ")
        else:
            assert deck_lines == []


def test_D5_four_body_sections_are_out_of_scope(tmp_path, capsys):
    text = "---\ndoctype: report\nformat: doc\ntitle: Note\n---\n\n## Sources\n\n- [S1] workshop.vtt, transcript\n\n"
    for i in range(1, 5):
        text += f'::: {{#body{i} .section intent="body"}}\n## Section {i}\n\nA finding. [S1 00:41]\n:::\n\n'
    path = tmp_path / "doc.md"
    path.write_text(text)
    code, out, err = _run_cli(path, tmp_path / "out", capsys)
    assert code == 0, (out, err)
    assert not any(" deck." in line for line in out.splitlines()), out


def test_D6_clean_reference_texts_have_no_findings(tmp_path, capsys):
    for filename in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(ROOT / "tests/judge" / filename))
        for kind in ("SLIDES", "DOC"):
            name = filename + kind
            path = tmp_path / (name + ".md")
            path.write_text(examples[kind])
            code, out, err = _run_cli(path, tmp_path / (name + "-out"), capsys)
            assert code == 0, (name, out, err)
            assert out.splitlines() == ["no findings"], (name, out)
