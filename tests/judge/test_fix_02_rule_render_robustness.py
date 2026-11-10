# Intent: detect narrow rule and rendering defects without changing established behaviour.
import importlib
import importlib.util
import re
import shutil
from pathlib import Path

import pytest
import yaml
from PIL import Image

from docla.checks import catalogue, engine
from docla.facts.layout import LayoutFacts
from docla.model import Document, Item, Provenance, Remedy, Rule, Section
from docla.render.marks import ElementMark


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name or importlib.util.find_spec(name) is not None:
            raise
        return None


def _require(module, name):
    assert module is not None and hasattr(module, name), f"{name} must exist"
    return getattr(module, name)


def _doc(section):
    return Document(front={}, format="slides", sections=[section])


def test_D1_empty_item_head_is_checked():
    assert hasattr(catalogue, "all_rules") and hasattr(engine, "run_checks")
    rule = Rule(
        id="judge.empty-head",
        title="Item text",
        origin="manual",
        strength="soft",
        status="active",
        severity="warning",
        tier="source",
        check={"kind": "text-pattern", "field": "items", "regex": r"\S", "must_match": True},
        remedy=Remedy.model_validate({"class": "tune", "hint": "Add text"}),
        provenance=Provenance(),
    )
    for head, expected in [("", [{"field": "items", "text": ""}]), (None, []), ("Lead", [])]:
        doc = _doc(Section(id="s1", intent="bullets", items=[Item(head=head, body="Text")]))
        findings = engine.run_checks([rule], engine.CheckContext(doc))
        assert [finding.measured for finding in findings] == expected


@pytest.mark.parametrize(
    "rows,expected", [(("[GAP: missing]",), ["missing"]), ([("North", "[GAP: owner]")], ["owner"])]
)
def test_D2_nested_tuples_are_searched(rows, expected):
    rules = _require(_module("docla.checks.gaps"), "RULES")
    rule = next(rule for rule in rules if rule.id == "source.gap-present")
    doc = _doc(Section(id="s1", intent="table", data={"rows": rows}))
    findings = engine.run_checks([rule], engine.CheckContext(doc))
    assert [finding.measured for finding in findings] == [{"gaps": expected}]


def test_D3_overlapping_figure_precedes_distant_figure():
    rules = _require(_module("docla.checks.adjacent"), "RULES")
    rule = next(rule for rule in rules if rule.id == "geo.figure-source")
    doc = _doc(Section(id="s1", intent="table"))

    def mark(role, y, height):
        return ElementMark(kind="element", role=role, id="s1", page=1, x=20, y=y, w=100, h=height)

    earlier = mark("figure", 10, 100)
    overlap = mark("figure", 220, 100)
    source = mark("figure-source", 200, 30)

    def run(marks):
        facts = LayoutFacts(pdf_sha256="", pages=[], words=[], shapes=[], marks=marks)
        return engine.run_checks([rule], engine.CheckContext(doc, facts))

    assert run([earlier, overlap, source]) == []
    assert [finding.measured["gap_pt"] for finding in run([earlier, source])] == [90.0]


def test_D4_rule_error_is_one_line_and_not_repeated(tmp_path, capsys):
    cli = _module("docla.cli")
    main = _require(cli, "main")
    neutral = Path(__file__).resolve().parents[2] / "src/docla/themes/neutral"
    theme = tmp_path / "theme"
    shutil.copytree(neutral, theme)
    authored = theme / "rules/authored"
    authored.mkdir(parents=True, exist_ok=True)
    (authored / "bad.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "test.no-provenance",
                "title": "Missing provenance",
                "origin": "manual",
                "strength": "soft",
                "status": "active",
                "severity": "warning",
                "tier": "source",
                "scope": {"format": "slides"},
                "check": {"kind": "empty-section"},
                "remedy": {"class": "report", "hint": "Add content."},
            }
        )
    )
    try:
        code = main(["theme", "test", "--theme", str(theme)])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert code == 1, (captured.out, captured.err)
    assert len(lines) == 5, lines
    assert lines[0].startswith("fail rules:") and "bad.yaml" in lines[0] and "provenance" in lines[0]
    for line, step in zip(lines[1:4], ("chooser", "doctypes", "fixtures"), strict=True):
        assert re.fullmatch(rf"ok {step}(?: \[\d+\])?", line)
    assert lines[4].startswith("fail gold:")
    assert "bad.yaml" not in lines[4] and "provenance" not in lines[4]


def test_D5_contact_labels_align_with_mixed_page_widths(tmp_path):
    contact_sheet = _require(_module("docla.facts.sheets"), "contact_sheet")
    colours = [(220, 30, 30), (30, 180, 30)]
    paths = [tmp_path / "wide.png", tmp_path / "narrow.png"]
    for path, size, colour in zip(paths, [(400, 225), (200, 225)], colours, strict=True):
        Image.new("RGB", size, colour).save(path)
    out = tmp_path / "sheet.png"
    assert contact_sheet(paths, ["1", "2"], out) == out
    with Image.open(out) as source:
        image = source.convert("RGB")
    pixels = list(image.getdata())
    spans = []
    for colour in colours:
        xs = [index % image.width for index, pixel in enumerate(pixels) if pixel == colour]
        assert xs
        spans.append((min(xs), max(xs)))
    label_xs = [index % image.width for index, pixel in enumerate(pixels) if pixel == (26, 26, 26)]
    assert label_xs
    assert all(any(left <= x <= right for left, right in spans) for x in label_xs)
    assert any(spans[1][0] <= x <= spans[1][1] for x in label_xs)


def test_D6_frozen_judges_pass():
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    files = [
        "test_b3_02_dsl.py",
        "test_b3_04_title_label.py",
        "test_b3_08_gap_present.py",
        "test_b3_16_figure_source.py",
        "test_b3_19_theme_test.py",
        "test_m4_03_sheets.py",
    ]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *[str(root / "tests" / "judge" / f) for f in files]],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
