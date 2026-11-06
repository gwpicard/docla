# Intent: Catalogue parser findings and preserve their existing parser and CLI behaviour.
import importlib.util
import runpy
from pathlib import Path

import pytest


def _public_module(name):
    try:
        return __import__(name, fromlist=["*"])
    except ImportError as error:
        if error.name == name or (error.name and name.startswith(error.name + ".")):
            try:
                spec = importlib.util.find_spec(error.name)
            except (ImportError, ModuleNotFoundError, ValueError):
                spec = None
            if spec is None:
                return None
        raise


catalogue = _public_module("docla.checks.catalogue")
engine = _public_module("docla.checks.engine")
parser = _public_module("docla.source.parser")
cli = _public_module("docla.cli")
model = _public_module("docla.model")

JUDGE = Path(__file__).resolve().parent
SEEDED = JUDGE.parent / "fixtures" / "seeded-defects"
IDS = [
    "source.appearance-in-source",
    "source.unknown-attribute",
    "source.parse-error",
    "source.missing-intent",
    "source.invalid-format",
]


def _rules():
    assert catalogue is not None and hasattr(catalogue, "parser_rules"), "catalogue.parser_rules must exist"
    return catalogue.parser_rules()


def _fixture(rule_id, outcome):
    path = SEEDED / rule_id / outcome / "doc.md"
    assert path.is_file(), f"seeded fixture must exist: {path}"
    return path


def _parse(text):
    assert parser is not None and hasattr(parser, "parse"), "docla.source.parser.parse must exist"
    return parser.parse(text)


def _check(path, out_dir, capsys):
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    try:
        code = cli.main(["check", str(path), "--out", str(out_dir)])
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_parser_rule_records():
    assert parser is not None and hasattr(parser, "SEVERITY")
    assert model is not None and hasattr(model, "Rule")
    rules = _rules()
    assert isinstance(rules, list)
    assert all(isinstance(rule, model.Rule) for rule in rules)
    assert [rule.id for rule in rules] == IDS
    for rule in rules:
        assert rule.tier == "source"
        assert rule.severity == parser.SEVERITY[rule.id.removeprefix("source.")]
        assert rule.remedy.class_ == ("engine" if rule.id == IDS[0] else "report")
        assert rule.title.strip() and rule.remedy.hint.strip()
        assert (rule.origin, rule.status, rule.strength) == (
            "manual", "active", "hard" if rule.severity == "error" else "soft"
        )
        assert rule.provenance.source == {"doc": "DESIGN.md", "section": "5.2"}


def test_D1_severity_is_read_from_parser_mapping(monkeypatch):
    assert parser is not None and hasattr(parser, "SEVERITY")
    monkeypatch.setitem(parser.SEVERITY, "unknown-attribute", "info")
    rule = next(rule for rule in _rules() if rule.id == "source.unknown-attribute")
    assert (rule.severity, rule.strength) == ("info", "soft")


def test_D2_parser_rules_are_not_engine_checks():
    rules = _rules()
    assert catalogue is not None and hasattr(catalogue, "all_rules")
    assert engine is not None and hasattr(engine, "CHECKS")
    assert not ({rule.id for rule in rules} & {rule.id for rule in catalogue.all_rules()})
    assert [rule.check for rule in rules] == [{"kind": "parser"}] * 5
    assert "parser" not in engine.CHECKS


def test_D3_appearance_fixture_parser_and_cli(tmp_path, capsys):
    fail = _fixture("source.appearance-in-source", "fail")
    passed = _fixture("source.appearance-in-source", "pass")
    _, findings = _parse(fail.read_text())
    assert [(f.rule_id, f.severity) for f in findings] == [("source.appearance-in-source", "error")]
    code, _, err = _check(fail, tmp_path / "fail", capsys)
    assert code == 2
    assert any(line.startswith("error source.appearance-in-source ") for line in err.splitlines())
    assert _parse(passed.read_text())[1] == []
    code, _, _ = _check(passed, tmp_path / "pass", capsys)
    assert code == 0


def test_D4_unknown_attribute_fixture_cli(tmp_path, capsys):
    fail = _fixture("source.unknown-attribute", "fail")
    passed = _fixture("source.unknown-attribute", "pass")
    document, findings = _parse(fail.read_text())
    assert len(document.sections) == 1 and document.sections[0].id
    assert [(f.rule_id, f.severity) for f in findings] == [("source.unknown-attribute", "warning")]
    code, out, _ = _check(fail, tmp_path / "fail", capsys)
    assert code == 0
    assert any(line.startswith(f"warning source.unknown-attribute {document.sections[0].id} ") for line in out.splitlines())
    code, out, _ = _check(passed, tmp_path / "pass", capsys)
    assert code == 0
    assert all("source.unknown-attribute" not in line for line in out.splitlines())


def test_D5_parser_severity_and_appearance_remedy_stay_unchanged():
    assert parser is not None and hasattr(parser, "SEVERITY")
    assert parser.SEVERITY == {
        "parse-error": "error", "missing-id": "warning", "missing-intent": "error",
        "appearance-in-source": "error", "unknown-attribute": "warning",
        "unknown-citation": "warning", "invalid-format": "error",
    }
    text = '---\nformat: slides\n---\n::: {#s1 .section intent="statement" color="red"}\n## A title\n:::\n'
    _, findings = _parse(text)
    assert [(f.rule_id, f.remedy.class_) for f in findings] == [("source.appearance-in-source", "report")]


@pytest.mark.parametrize("judge_file", ["test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"])
@pytest.mark.parametrize("name", ["SLIDES", "DOC"])
def test_D5_existing_clean_examples_still_print_no_findings(judge_file, name, tmp_path, capsys):
    examples = runpy.run_path(str(JUDGE / judge_file))
    source = tmp_path / "doc.md"
    source.write_text(examples[name])
    code, out, _ = _check(source, tmp_path / "out", capsys)
    assert code == 0
    assert out.splitlines() == ["no findings"]
