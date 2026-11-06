# Intent: Check document sections against their doctype outline only when requested.
import json
import runpy
from pathlib import Path

from docla.model import Document, Section
from docla.source.parser import parse

try:
    import docla.doctypes as doctypes
except ImportError as error:
    if error.name not in ("docla", "docla.doctypes"):
        raise
    doctypes = None

try:
    from docla.checks import catalogue, engine
except ImportError as error:
    if error.name not in ("docla.checks", "docla.checks.catalogue", "docla.checks.engine"):
        raise
    catalogue = engine = None

try:
    from docla import cli
except ImportError as error:
    if error.name not in ("docla", "docla.cli"):
        raise
    cli = None

HERE = Path(__file__).resolve().parent
SEEDED = HERE.parent / "fixtures" / "seeded-defects" / "source.outline-conforms"


def _conformance(doc):
    assert doctypes is not None and hasattr(doctypes, "conformance") and hasattr(doctypes, "Gap")
    return doctypes.conformance(doc, doctypes.load_doctypes()["pitch-deck"])


def _doc(names):
    return Document(
        front={"doctype": "pitch-deck"},
        format="slides",
        sections=[Section(id=f"s{i}", intent="statement", section=name) for i, name in enumerate(names)],
    )


def _run(argv, capsys):
    assert cli is not None and hasattr(cli, "main")
    try:
        code = cli.main(argv)
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_conformance_counts_and_order():
    assert _conformance(_doc(["opener", "content", "content", "ask"])) == []
    for names, expected in [
        (["opener", "content"], [("missing", "ask")]),
        (["opener", "ask", "content"], [("order", "content")]),
        (["opener", "ask"], [("repeat", "content")]),
    ]:
        gaps = _conformance(_doc(names))
        assert [(gap.kind, gap.section) for gap in gaps] == expected
        assert all(isinstance(gap, doctypes.Gap) and gap.section in gap.message for gap in gaps)


def test_D1_ignores_unknown_sections_and_orders_all_gaps():
    gaps = _conformance(_doc(["ask", "unknown", None, "content", "content"] + ["content"] * 15))
    assert [(gap.kind, gap.section) for gap in gaps] == [
        ("missing", "opener"),
        ("order", "content"),
        ("repeat", "content"),
    ]
    assert all(gap.section in gap.message for gap in gaps)


def test_D2_unlabelled_frozen_slides_are_ignored():
    slides = runpy.run_path(str(HERE / "test_m1_17_cli_build_check.py"))["SLIDES"]
    doc, findings = parse(slides)
    assert findings == []
    assert [(gap.kind, gap.section) for gap in _conformance(doc)] == [
        ("missing", "opener"),
        ("missing", "ask"),
        ("repeat", "content"),
    ]


def test_D3_document_rules_are_separate():
    assert catalogue is not None and hasattr(catalogue, "document_rules")
    rules = catalogue.document_rules()
    assert [(r.id, r.severity, r.tier, r.remedy.class_) for r in rules] == [
        ("source.outline-conforms", "error", "source", "restructure")
    ]
    assert not ({r.id for r in rules} & {r.id for r in catalogue.all_rules()})


def test_D3_rule_findings_have_distinct_fingerprints_and_ignore_unknown_doctypes():
    assert catalogue is not None and hasattr(catalogue, "document_rules") and engine is not None
    rules = catalogue.document_rules()
    doc = _doc([])
    findings = engine.run_checks(rules, engine.CheckContext(doc))
    assert [f.measured for f in findings] == [
        {"kind": "missing", "section": "opener"},
        {"kind": "missing", "section": "ask"},
        {"kind": "repeat", "section": "content"},
    ]
    assert len({f.fingerprint for f in findings}) == 3
    assert [f.section_id for f in findings[:2]] == [None, None]
    for front in ({}, {"doctype": "not-packaged"}):
        doc.front = front
        assert engine.run_checks(rules, engine.CheckContext(doc)) == []


def test_D4_outline_flag_checks_seeded_pair(tmp_path, capsys):
    for side in ("fail", "pass"):
        fixture = SEEDED / side / "doc.md"
        assert fixture.is_file(), str(fixture)
        out_dir = tmp_path / side
        code, out, _ = _run(["check", str(fixture), "--outline", "--out", str(out_dir)], capsys)
        lines = [line for line in out.splitlines() if line.startswith("error source.outline-conforms ")]
        assert code == (1 if side == "fail" else 0), out
        if side == "fail":
            assert len(lines) == 1 and "ask" in lines[0]
            report = json.loads((out_dir / "doc.findings.json").read_text())
            assert [f["measured"] for f in report if f["rule_id"] == "source.outline-conforms"] == [
                {"kind": "missing", "section": "ask"}
            ]
        else:
            assert lines == []
    _, out, _ = _run(["check", str(SEEDED / "fail" / "doc.md"), "--out", str(tmp_path / "plain")], capsys)
    assert "source.outline-conforms" not in out


def test_D4_outline_runs_when_composition_fails(tmp_path, capsys):
    source = tmp_path / "unknown.md"
    source.write_text(
        '---\ndoctype: pitch-deck\nformat: slides\n---\n\n'
        '::: {#s1 .section intent="unknown" section="opener"}\n## Heading\n:::\n'
    )
    code, out, _ = _run(["check", str(source), "--outline", "--out", str(tmp_path / "out")], capsys)
    assert code == 1
    assert any(line.startswith("error source.outline-conforms ") and "ask" in line for line in out.splitlines())


def test_D5_plain_check_preserves_frozen_clean_texts(tmp_path, capsys):
    for file in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(HERE / file))
        for name in ("SLIDES", "DOC"):
            source = tmp_path / f"{file}-{name}.md"
            source.write_text(examples[name])
            code, out, _ = _run(["check", str(source), "--out", str(tmp_path / f"out-{file}-{name}")], capsys)
            assert (code, out.splitlines()) == (0, ["no findings"]), (file, name, out)
