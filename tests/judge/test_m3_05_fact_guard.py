# Intent: Guard rewritten sections against unsupported facts and report facts lost in rewrites.
import importlib.util
import runpy
from pathlib import Path

import pytest

from docla import cli
from docla.checks import catalogue
from docla.model import Citation, Document, Item, Patch, PatchOp, Section
from docla.source.parser import parse
from docla.source.patches import PatchRejected, apply_patch

try:
    import docla.loop.guards as guards
except ImportError as error:
    if error.name not in ("docla.loop", "docla.loop.guards"):
        raise
    if error.name == "docla.loop.guards" and importlib.util.find_spec("docla.loop") is None:
        raise
    guards = None

ROOT = Path(__file__).resolve().parents[2]
SEEDED = ROOT / "tests" / "fixtures" / "seeded-defects"


def _interface(name):
    assert guards is not None and hasattr(guards, name), f"docla.loop.guards.{name} must exist"
    return getattr(guards, name)


def _doc(body, **kwargs):
    section = Section(id="s1", intent="bullets", title="Pilot", items=[Item(body=body)], **kwargs)
    return Document(front={}, format="slides", sections=[section]), section


def test_D1_guard_and_patch_rejection():
    guard_type = _interface("FactGuard")
    doc, section = _doc("the pipeline drops 14% of readings")
    guard = guard_type(["the pipeline drops 12% of readings"])
    assert guard(doc, section) is False
    assert guard.unsupported == ["14%"]
    supported = guard_type(["14% of readings"])
    assert supported(doc, section) is True
    assert supported.unsupported == []
    original, _ = _doc("the pipeline drops 12% of readings")
    patch = Patch(
        base_rev=0,
        author="ai",
        reason="rewrite",
        ops=[
            PatchOp(
                op="set_fields", section_id="s1", fields={"items": [{"body": "the pipeline drops 14% of readings"}]}
            )
        ],
    )
    with pytest.raises(PatchRejected) as rejected:
        apply_patch(original, patch, fact_guard=guard)
    assert rejected.value.code == "fact-unsupported"


def test_D2_fields_number_words_and_citations():
    guard_type = _interface("FactGuard")
    doc, section = _doc("Maria Jensen leads it from month 1")
    section.items[0].citations = [Citation(key="S1", locator="00:41")]
    guard = guard_type(["Maria Jensen leads the pilot", "month one"], citation_keys=["S1"])
    assert guard(doc, section) is True
    assert guard.unsupported == []
    section.items[0].citations.append(Citation(key="S9", locator="p.4"))
    assert guard(doc, section) is False
    assert guard.unsupported == ["cite:S9"]


def test_D3_calculations_require_supported_operands_and_correct_result():
    guard_type = _interface("FactGuard")
    evidence = ["7 of 50 vessels", "12 and 25 sites"]
    for result, note in [
        ("14%", "percentage(7, 50) = 14%"),
        ("37", "sum(12, 25) = 37"),
        ("13", "difference(25, 12) = 13"),
        ("2", "ratio(50, 25) = 2"),
    ]:
        doc, section = _doc(f"Result is {result}", note=f"calc: {note}")
        guard = guard_type(evidence)
        assert guard(doc, section) is True, note
        assert guard.unsupported == []
    for result, note in [("15%", "percentage(7, 50) = 15%"), ("38", "sum(12, 26) = 38")]:
        doc, section = _doc(f"Result is {result}", note=f"calc: {note}")
        guard = guard_type(evidence)
        assert guard(doc, section) is False
        assert guard.unsupported == [result]


def test_D4_rules_and_kept_facts():
    rules = _interface("RULES")
    assert [r.id for r in rules] == ["source.fact-support", "source.facts-kept"]
    for rule in rules:
        assert (rule.severity, rule.tier, rule.remedy.class_) == ("error", "source", "redraft")
        assert (rule.origin, rule.strength, rule.status, rule.check) == (
            "manual",
            "hard",
            "active",
            {"kind": "fact-guard"},
        )
        assert rule.remedy.hint
    before = Section(id="s1", intent="bullets", title="Three integrity concerns across the North Sea fleet")
    after = Section(
        id="s1", intent="bullets", title="Integrity concerns", items=[Item(body="across the North Sea fleet")]
    )
    assert _interface("kept_facts")(before, after) == ["north sea"]


def test_D4_seeded_rewrites():
    check_rewrite = _interface("check_rewrite")
    for rule_id, token in [("source.fact-support", "14%"), ("source.facts-kept", "north sea")]:
        for kind in ("fail", "pass"):
            folder = SEEDED / rule_id / kind
            documents = []
            for name in ("before.md", "after.md"):
                path = folder / name
                assert path.is_file(), str(path)
                doc, findings = parse(path.read_text())
                assert not [f for f in findings if f.severity == "error"], (path, findings)
                documents.append(doc)
            assert {s.id for s in documents[1].sections} == {s.id for s in documents[0].sections}
            hits = [f for f in check_rewrite(*documents) if f.rule_id == rule_id]
            if kind == "fail":
                assert len(hits) == 1
                assert token in hits[0].measured["tokens"]
                assert token in hits[0].message
                assert hits[0].section_id in {s.id for s in documents[1].sections}
            else:
                assert hits == []


def test_D5_catalogue_excludes_rewrite_rules():
    ids = {rule.id for rule in catalogue.all_rules()}
    assert "source.fact-support" not in ids
    assert "source.facts-kept" not in ids


def test_D5_cli_clean_existing_examples(tmp_path, capsys):
    for filename in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(ROOT / "tests" / "judge" / filename))
        for name in ("SLIDES", "DOC"):
            source = tmp_path / f"{filename}-{name}.md"
            source.write_text(examples[name])
            try:
                code = cli.main(["check", str(source), "--out", str(tmp_path / f"out-{filename}-{name}")])
            except SystemExit as error:
                code = error.code
            captured = capsys.readouterr()
            assert code == 0, captured.err
            assert captured.out.splitlines() == ["no findings"]
