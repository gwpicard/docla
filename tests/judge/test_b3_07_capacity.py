# Intent: report section content that exceeds the drawing component's maximum capacity.
import importlib
import importlib.util
import json
import runpy
from pathlib import Path

from docla import cli
from docla.checks import catalogue, engine, source
from docla.model import Document, Item, Section
from docla.render import components
from docla.source.parser import parse

try:
    capacity = importlib.import_module("docla.checks.capacity")
except ImportError as error:
    if error.name != "docla.checks.capacity" or importlib.util.find_spec("docla.checks.capacity") is not None:
        raise
    capacity = None

JUDGE = Path(__file__).resolve().parent
SEEDED = JUDGE.parent / "fixtures" / "seeded-defects"


def _rules():
    assert capacity is not None and hasattr(capacity, "RULES"), "docla.checks.capacity.RULES must exist"
    return capacity.RULES


def _check(doc):
    return engine.run_checks(_rules(), engine.CheckContext(doc))


def _run(argv, capsys):
    try:
        code = cli.main(argv)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
    captured = capsys.readouterr()
    return code, captured.out


def test_D1_measures_count_section_content():
    assert hasattr(components, "MEASURES"), "docla.render.components.MEASURES must exist"
    measures = components.MEASURES
    assert set(measures) == {
        "title_words",
        "items",
        "item_chars",
        "paragraphs",
        "columns",
        "rows",
        "categories",
        "series",
    }
    bullets = Section(
        intent="bullets",
        title="What the workshop found",
        items=[Item(head="Corrosion", body="x" * 30), Item(body="Short"), Item(body="y", sub=["a", "b", "c"])],
        paragraphs=["One.", "Two."],
    )
    assert {key: fn(bullets) for key, fn in measures.items()} == {
        "title_words": 4,
        "items": 3,
        "item_chars": 39,
        "paragraphs": 2,
        "columns": 0,
        "rows": 3,
        "categories": 0,
        "series": 0,
    }
    table = Section(
        intent="table",
        data={
            "columns": ["A", "B", "C"],
            "rows": [[1, 2, 3], [4, 5, 6]],
            "categories": ["N", "S"],
            "series": [{"name": "Now", "values": [1, 2]}],
        },
    )
    assert {
        key: measures[key](table) for key in ("columns", "rows", "categories", "series", "items", "title_words")
    } == {
        "columns": 3,
        "rows": 2,
        "categories": 2,
        "series": 1,
        "items": 0,
        "title_words": 0,
    }
    assert all(type(fn(bullets)) is int and type(fn(table)) is int for fn in measures.values())
    malformed = Section(intent="table", data={"columns": "bad", "rows": None, "categories": {}, "series": 1})
    assert [measures[key](malformed) for key in ("columns", "rows", "categories", "series")] == [0, 0, 0, 0]


def test_D2_catalogue_order_and_rule_metadata():
    ids = [rule.id for rule in catalogue.all_rules()]
    first = [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
        "source.intent-known",
    ]
    assert ids[:7] == first
    assert [rule.id for rule in catalogue.m1_rules()] == first[:6]
    assert len(source.RULES) == 2
    assert ids.count("source.capacity") == 1
    assert ids.index("source.capacity") > max(ids.index(rule.id) for rule in [*catalogue.m1_rules(), *source.M2_RULES])
    rule = next(rule for rule in catalogue.all_rules() if rule.id == "source.capacity")
    assert (rule.severity, rule.tier, rule.remedy.class_) == ("warning", "source", "redraft")


def test_D3_seeded_capacity_and_maxima_only():
    _rules()
    for kind in ("fail", "pass"):
        path = SEEDED / "source.capacity" / kind / "doc.md"
        assert path.is_file(), f"missing seeded fixture: {path}"
        doc, parsed = parse(path.read_text())
        assert parsed == []
        hits = _check(doc)
        if kind == "pass":
            assert hits == []
        else:
            assert len(hits) == 1
            hit = hits[0]
            assert (hit.rule_id, hit.severity, hit.section_id, hit.measured) == (
                "source.capacity",
                "warning",
                doc.sections[0].id,
                {"measure": "items", "value": 7, "max": 6},
            )
            assert all(word in hit.message for word in ("items", "7", "6", "bullets"))
    process = Section(id="p", intent="process", title="How we work", items=[Item(body="Plan"), Item(body="Build")])
    assert _check(Document(front={}, format="slides", sections=[process])) == []
    bullets = Section(
        id="b", intent="bullets", title="Findings", items=[Item(body="x" * 200)] + [Item(body="Short")] * 7
    )
    hits = _check(Document(front={}, format="slides", sections=[bullets]))
    assert len(hits) == 2
    assert {hit.measured["measure"] for hit in hits} == {"items", "item_chars"}
    assert len({hit.fingerprint for hit in hits}) == 2


def test_D4_cli_reports_seeded_fixtures(tmp_path, capsys):
    _rules()
    for kind in ("fail", "pass"):
        path = SEEDED / "source.capacity" / kind / "doc.md"
        assert path.is_file(), f"missing seeded fixture: {path}"
        doc, parsed = parse(path.read_text())
        assert parsed == []
        out_dir = tmp_path / kind
        code, out = _run(["check", str(path), "--out", str(out_dir)], capsys)
        report = out_dir / "doc.findings.json"
        assert report.is_file(), out
        hits = [f for f in json.loads(report.read_text()) if f["rule_id"] == "source.capacity"]
        if kind == "fail":
            assert any(line.startswith(f"warning source.capacity {doc.sections[0].id} ") for line in out.splitlines())
            assert len(hits) == 1
            assert hits[0]["measured"] == {"measure": "items", "value": 7, "max": 6}
        else:
            assert code == 0
            assert hits == []


def test_D5_existing_clean_and_geometry_checks(tmp_path, capsys):
    for judge in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        texts = runpy.run_path(str(JUDGE / judge))
        for name in ("SLIDES", "DOC"):
            path = tmp_path / f"{judge}-{name}.md"
            path.write_text(texts[name])
            code, out = _run(["check", str(path), "--out", str(tmp_path / f"out-{judge}-{name}")], capsys)
            assert (code, out.splitlines()) == (0, ["no findings"])
    path = SEEDED / "geo.text-fits" / "fail" / "doc.md"
    code, out = _run(["check", str(path), "--out", str(tmp_path / "geo")], capsys)
    assert code == 1
    assert any(line.startswith("error geo.text-fits ") for line in out.splitlines())
