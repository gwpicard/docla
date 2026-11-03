# Intent: `docla build` writes a PDF and `docla check` reports the M1 rules' findings as lines and as JSON.
import json
import re
from pathlib import Path

from pydantic import TypeAdapter

try:
    from docla import cli
except ImportError as error:
    if error.name != "docla" and not str(error.name).startswith("docla."):
        raise
    cli = None

try:
    from docla.checks import catalogue
except ImportError as error:
    if error.name not in ("docla.checks", "docla.checks.catalogue"):
        raise
    catalogue = None

from docla.model import Finding

SEEDED = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects"

SLIDES = """---
doctype: pitch-deck
format: slides
title: Readout
---

## Sources

- [S1] workshop.vtt, transcript

::: {#aaaa1 .section intent="statement"}
## One pilot is enough
:::

::: {#aaaa2 .section intent="bullets"}
## Why it works

- Short intervals catch drift early. [S1 00:41]
- Cheap to repeat.
:::
"""

DOC = """---
doctype: report
format: doc
title: Note
---

## Sources

- [S1] workshop.vtt, transcript

::: {#bbbb1 .section intent="body"}
## Findings

The pipeline drops some readings, and the team agreed to measure how many. [S1 00:41]
:::
"""


def _run(argv, capsys):
    """Run cli.main(argv); return (exit code, stdout, stderr)."""
    assert cli is not None and hasattr(cli, "main"), "docla.cli.main must exist"
    try:
        code = cli.main(argv)
    except SystemExit as exit_:
        code = exit_.code if isinstance(exit_.code, int) else (0 if exit_.code is None else 1)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def _media_boxes(pdf):
    found = re.findall(rb"/MediaBox\s*\[([^\]]*)\]", pdf.read_bytes())
    return [tuple(round(float(n), 1) for n in box.split()) for box in found]


def test_D1_build_slides_prints_path_and_writes_two_slide_pages(tmp_path, capsys):
    source = _write(tmp_path, "deck.md", SLIDES)
    out_dir = tmp_path / "out"
    code, out, _ = _run(["build", str(source), "--out", str(out_dir)], capsys)
    pdf = out_dir / "deck.pdf"
    assert code == 0
    assert str(pdf) in out
    assert _media_boxes(pdf) == [(0.0, 0.0, 960.0, 540.0)] * 2


def test_D1_build_doc_writes_a4_pages(tmp_path, capsys):
    source = _write(tmp_path, "note.md", DOC)
    out_dir = tmp_path / "out"
    code, out, _ = _run(["build", str(source), "--out", str(out_dir)], capsys)
    boxes = _media_boxes(out_dir / "note.pdf")
    assert code == 0
    assert str(out_dir / "note.pdf") in out
    assert boxes == [(0.0, 0.0, 595.3, 841.9)]


def test_D1_build_defaults_to_build_folder_and_replaces_earlier_render(tmp_path, capsys):
    source = _write(tmp_path, "deck.md", SLIDES)
    first = _run(["build", str(source)], capsys)
    second = _run(["build", str(source)], capsys)
    assert first[0] == 0
    assert second[0] == 0
    assert str(tmp_path / "build" / "deck.pdf") in second[1]
    assert (tmp_path / "build" / "deck.pdf").is_file()


def test_D2_check_text_fits_fail_fixture_reports_error_line(tmp_path, capsys):
    fixture = SEEDED / "geo.text-fits" / "fail" / "doc.md"
    code, out, _ = _run(["check", str(fixture), "--out", str(tmp_path / "out")], capsys)
    assert code == 1
    assert any(line.startswith("error geo.text-fits ") for line in out.splitlines()), out


def test_D3_check_clean_slides_and_doc_report_no_findings(tmp_path, capsys):
    for name, text in (("deck.md", SLIDES), ("note.md", DOC)):
        source = _write(tmp_path, name, text)
        code, out, _ = _run(["check", str(source), "--out", str(tmp_path / ("out-" + name))], capsys)
        assert code == 0, (name, out)
        assert "no findings" in out.splitlines(), (name, out)


def test_D4_findings_json_matches_printed_lines(tmp_path, capsys):
    fixture = SEEDED / "geo.text-fits" / "fail" / "doc.md"
    out_dir = tmp_path / "out"
    _, out, _ = _run(["check", str(fixture), "--out", str(out_dir)], capsys)
    raw = json.loads((out_dir / "doc.findings.json").read_text())
    findings = TypeAdapter(list[Finding]).validate_python(raw)
    expected = [f"{f.severity} {f.rule_id} {f.section_id or '-'} {f.message}" for f in findings]
    assert len(findings) >= 1
    assert out.splitlines() == expected


def test_D4_findings_json_is_empty_list_when_clean(tmp_path, capsys):
    source = _write(tmp_path, "deck.md", SLIDES)
    out_dir = tmp_path / "out"
    _run(["check", str(source), "--out", str(out_dir)], capsys)
    assert json.loads((out_dir / "deck.findings.json").read_text()) == []


def test_D5_build_unknown_intent_exits_2_and_names_intent(tmp_path, capsys):
    source = _write(tmp_path, "deck.md", SLIDES.replace('intent="bullets"', 'intent="no-such-intent"'))
    code, _, err = _run(["build", str(source), "--out", str(tmp_path / "out")], capsys)
    assert code == 2
    assert "no-such-intent" in err
    assert not (tmp_path / "out" / "deck.pdf").exists()


def test_D5_build_invalid_yaml_front_matter_exits_2(tmp_path, capsys):
    valid = _write(tmp_path, "valid.md", SLIDES)
    assert _run(["build", str(valid), "--out", str(tmp_path / "ok")], capsys)[0] == 0
    source = _write(tmp_path, "deck.md", SLIDES.replace("title: Readout", "title: [unclosed"))
    code, _, err = _run(["build", str(source), "--out", str(tmp_path / "out")], capsys)
    assert code == 2
    assert err.strip() != ""
    assert not (tmp_path / "out" / "deck.pdf").exists()


def test_D6_m1_rules_lists_ids_in_order_with_seeded_fixtures():
    assert catalogue is not None and hasattr(catalogue, "m1_rules"), "docla.checks.catalogue.m1_rules must exist"
    ids = [rule.id for rule in catalogue.m1_rules()]
    assert ids == [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
    ]
    for rule_id in ids:
        for kind in ("fail", "pass"):
            folder = SEEDED / rule_id / kind
            assert (folder / "doc.md").is_file() or (folder / "main.typ").is_file(), folder
