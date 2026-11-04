# Intent: `docla check` runs source rules when a section cannot be drawn; an unknown intent is `source.intent-known`.
import json
from pathlib import Path

import pytest

try:
    from docla import cli
except ImportError as error:
    if error.name != "docla" and not str(error.name).startswith("docla."):
        raise
    cli = None

from docla.model import Item, Section

SEEDED = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects"


def _fixture(rule: str, kind: str) -> Path:
    path = SEEDED / rule / kind / "doc.md"
    assert path.exists(), f"fixture {path} must exist"
    return path


def _run(file: Path, out: Path, capsys, command: str = "check"):
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    code = cli.main([command, str(file), "--out", str(out)])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _component_for():
    try:
        from docla.render import compose
    except ImportError as error:
        if error.name not in ("docla.render", "docla.render.compose"):
            raise
        compose = None
    assert compose is not None and hasattr(compose, "component_for"), "compose.component_for must exist"
    return compose.component_for


def test_D1_check_runs_source_rules_when_composing_fails(tmp_path, capsys):
    code, out, _ = _run(_fixture("source.citations-resolve", "fail"), tmp_path, capsys)
    lines = out.splitlines()
    assert code == 1
    assert any(line.startswith("error source.citations-resolve") for line in lines)
    assert any(line.startswith("error source.intent-known") for line in lines)


def test_D2_fail_fixture_gives_one_finding_with_measured(tmp_path, capsys):
    code, out, _ = _run(_fixture("source.intent-known", "fail"), tmp_path, capsys)
    assert code == 1
    found = [
        f for f in json.loads((tmp_path / "doc.findings.json").read_text()) if f["rule_id"] == "source.intent-known"
    ]
    assert len(found) == 1
    assert found[0]["measured"] == {"intent": "timeline", "format": "slides"}
    assert len([line for line in out.splitlines() if " source.intent-known " in line]) == 1


@pytest.mark.parametrize("kind", ["pass"])
def test_D2_pass_fixture_gives_no_intent_known_finding(tmp_path, capsys, kind):
    _, out, _ = _run(_fixture("source.intent-known", kind), tmp_path, capsys)
    assert "source.intent-known" not in out
    findings = json.loads((tmp_path / "doc.findings.json").read_text())
    assert [f for f in findings if f["rule_id"] == "source.intent-known"] == []


def test_D3_findings_file_matches_printed_lines_and_no_pdf(tmp_path, capsys):
    _, out, _ = _run(_fixture("source.intent-known", "fail"), tmp_path, capsys)
    findings = json.loads((tmp_path / "doc.findings.json").read_text())
    printed = [line for line in out.splitlines() if line.strip()]
    assert len(findings) == len(printed) >= 1
    for finding, line in zip(findings, printed, strict=True):
        assert line.startswith(f"{finding['severity']} {finding['rule_id']} ")
    assert list(tmp_path.glob("*.pdf")) == []


def test_D4_build_still_exits_2_naming_intent(tmp_path, capsys):
    code, _, err = _run(_fixture("source.intent-known", "fail"), tmp_path, capsys, command="build")
    assert code == 2
    assert "timeline" in err


def test_D5_component_for_known_intent():
    section = Section(id="s1", intent="bullets", title="T", items=[Item(body="x")])
    assert _component_for()(section, "slides") == "bullets"


def test_D5_component_for_unknown_intent_is_none():
    section = Section(id="s1", intent="timeline", title="T", items=[Item(body="x")])
    assert _component_for()(section, "slides") is None


def test_D5_component_for_named_component_attribute():
    section = Section(id="s1", intent="timeline", component="bullets", title="T", items=[Item(body="x")])
    assert _component_for()(section, "slides") == "bullets"
