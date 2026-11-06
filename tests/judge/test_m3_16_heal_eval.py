# Intent: the heal eval exercises forty seeded slide defects and reports reproducible outcomes.
import importlib
import importlib.util
import json
import re
import runpy
from collections import Counter
from pathlib import Path

from docla import cli
from docla.model import Patch, PatchOp
from docla.render.compose import component_for
from docla.source.parser import parse
from docla.source.patches import apply_patch
from docla.source.serialiser import serialise

try:
    heal = importlib.import_module("docla.evals.heal")
except ImportError as error:
    if error.name not in ("docla.evals", "docla.evals.heal"):
        raise
    heal = None

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests/fixtures/heal-eval"
RULES = {
    "overflow": "geo.text-fits",
    "long-title": "geo.text-fits",
    "banned-term": "source.banned-terms",
    "drift": "source.terminology-drift",
    "missing-citation": "source.uncited-figure",
}


def _cases():
    assert heal is not None and hasattr(heal, "load_cases"), "docla.evals.heal.load_cases must exist"
    return heal.load_cases(CASES)


def _run(argv, capsys):
    try:
        code = cli.main(argv)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _text(section):
    values = [section.title or "", *section.paragraphs, *section.code]
    values.extend(value or "" for value in (section.note, section.spoken, section.source_line))
    for item in section.items:
        values.extend([item.head or "", item.body, *item.sub])
    return "\n".join(values)


def test_D1_cases_have_the_required_distribution_and_valid_documents():
    cases = _cases()
    assert len(cases) == 40
    assert len({case.id for case in cases}) == 40
    assert Counter(case.kind for case in cases) == {kind: 8 for kind in RULES}
    components = set()
    overflow_components = set()
    title_components = set()
    for case in cases:
        assert case.rule == RULES[case.kind]
        assert str(case.file) == f"{case.id}.md"
        source = CASES / case.file
        assert source.is_file()
        doc, findings = parse(source.read_text())
        assert not [finding for finding in findings if finding.severity == "error"], case.id
        assert doc.format == "slides" and len(doc.sections) == 1 and doc.sections[0].id
        assert 1 <= len(case.facts) <= 4
        assert all(fact in _text(doc.sections[0]) for fact in case.facts), case.id
        component = component_for(doc.sections[0], "slides")
        components.add(component)
        if case.kind == "overflow":
            overflow_components.add(component)
        if case.kind == "long-title":
            title_components.add(component)
    assert len(components - {None}) >= 6
    assert len(overflow_components - {None}) >= 4
    assert {"bullets", "cover", "chapter-break"} <= title_components


def test_D2_each_seeded_defect_is_reported_without_unrelated_findings(tmp_path, capsys):
    for case in _cases():
        source = CASES / case.file
        doc, _ = parse(source.read_text())
        section_id = doc.sections[0].id
        output = tmp_path / case.id
        _, out, err = _run(["check", str(source), "--out", str(output)], capsys)
        severity = "error" if case.kind in ("overflow", "long-title", "banned-term") else "warning"
        assert any(line.startswith(f"{severity} {case.rule} {section_id} ") for line in out.splitlines()), (
            case.id,
            out,
            err,
        )
        allowed = {case.rule}
        if case.kind in ("overflow", "long-title"):
            allowed.update({"source.capacity", "geo.in-safe-area"})
        assert all(len(line.split()) >= 2 and line.split()[1] in allowed for line in out.splitlines()), (case.id, out)
        findings_file = output / f"{source.stem}.findings.json"
        assert findings_file.is_file(), (case.id, out, err)
        findings = json.loads(findings_file.read_text())
        if case.kind in ("overflow", "long-title"):
            roles = [finding["role"] for finding in findings if finding["rule_id"] == "geo.text-fits"]
            assert any((role == "title") == (case.kind == "long-title") for role in roles), case.id


def test_D3_repairs_clear_all_findings_and_keep_the_facts(tmp_path, capsys):
    for case in _cases():
        doc, _ = parse((CASES / case.file).read_text())
        patch = Patch(
            base_rev=doc.rev,
            author="ai",
            reason="repair",
            ops=[PatchOp(op="set_fields", section_id=doc.sections[0].id, fields=case.repair)],
        )
        repaired = apply_patch(doc, patch)
        assert all(fact in _text(repaired.sections[0]) for fact in case.facts), case.id
        source = tmp_path / f"{case.id}.md"
        source.write_text(serialise(repaired))
        code, out, err = _run(["check", str(source), "--out", str(tmp_path / case.id)], capsys)
        assert code == 0 and out.splitlines() == ["no findings"], (case.id, out, err)


def test_D4_offline_eval_reports_all_cases_deterministically(tmp_path, capsys):
    cases = _cases()
    outputs = [tmp_path / "first/RESULTS.md", tmp_path / "second/RESULTS.md"]
    for output in outputs:
        code, out, err = _run(["eval", "heal", "--cases", str(CASES), "--out", str(output)], capsys)
        assert code == 0, (out, err)
        assert output.is_file()
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    text = outputs[0].read_text()
    lines = text.splitlines()
    assert lines[:2] == ["# Heal eval", ""]
    for line in (
        "Mode: offline",
        "Cases: 40",
        "Cleared in at most 3 attempts: 40 / 40 (100.0%)",
        "Cost: $0.0000",
        "Gate: met",
    ):
        assert line in lines
    assert any(re.fullmatch(r"Mean attempts: \d+\.\d{2}", line) for line in lines)
    assert any(re.fullmatch(r"Facts kept: (\d+) / \1 \(100\.0%\)", line) for line in lines)
    assert "| Case | Kind | Rule | Status | Attempts | Facts kept |" in lines
    for case in cases:
        assert sum(line.startswith(f"| {case.id} |") for line in lines) == 1


def test_D5_live_requires_opt_in_before_transport_or_output(tmp_path, capsys, monkeypatch):
    assert importlib.util.find_spec("docla.write") is not None, "docla.write must exist"
    write = importlib.import_module("docla.write")
    assert hasattr(write, "live_transport"), "docla.write.live_transport must exist"
    calls = []
    monkeypatch.setattr(write, "live_transport", lambda: calls.append("called"))
    monkeypatch.delenv("DOCLA_LIVE", raising=False)
    output = tmp_path / "results/RESULTS.md"
    code, _, err = _run(["eval", "heal", "--live", "--out", str(output)], capsys)
    assert code == 2 and "DOCLA_LIVE=1" in err
    assert not output.exists() and calls == []


def test_D6_existing_clean_slide_and_document_examples_still_check_clean(tmp_path, capsys):
    for filename in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(ROOT / "tests/judge" / filename))
        for name in ("SLIDES", "DOC"):
            source = tmp_path / f"{filename}-{name}.md"
            source.write_text(examples[name])
            code, out, err = _run(["check", str(source), "--out", str(tmp_path / (filename + name))], capsys)
            assert code == 0 and out.splitlines() == ["no findings"], (filename, name, out, err)
