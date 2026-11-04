# Intent: chart sections render proportional, capacity-aware slides with the declared roles.
import re
from pathlib import Path

import pytest
import yaml

from docla import cli
from docla.model import Document, Item, Section
from docla.render import chooser, components, marks, swatch
from docla.source.serialiser import serialise
from docla.theme import neutral_theme

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/components/chart.yaml"


def _manifests():
    assert hasattr(components, "all_manifests"), "docla.render.components.all_manifests must exist"
    result = components.all_manifests()
    assert "chart" in result, "chart manifest must exist"
    return result


def _fixture():
    _manifests()
    assert FIXTURE.is_file(), "chart fixture must exist"
    return Section.model_validate(yaml.safe_load(FIXTURE.read_text()))


def _doc(section):
    return Document(front={"doctype": "pitch-deck", "title": "Chart"}, format="slides", sections=[section])


def _render(section, tmp_path):
    _manifests()
    assert section.id
    tmp_path.mkdir(parents=True, exist_ok=True)
    return swatch.swatch(_doc(section), section.id, tmp_path, theme=neutral_theme()).facts


def _section(count=3, series=1, chart_type="bar"):
    return Section(id="chart1", intent="chart", title="Results", data={
        "type": chart_type,
        "categories": [f"C{i}" for i in range(count)],
        "series": [{"name": f"S{j}", "values": [2 ** (i % 3) for i in range(count)]}
                   for j in range(series)],
    })


def test_D1_chart_manifest_and_packaged_manifests():
    manifest = _manifests()["chart"]
    assert manifest.name == "chart"
    assert manifest.format == "slides"
    assert manifest.intents == ["chart"]
    assert manifest.capacity == {"title_words": (1, 8), "categories": (1, 6), "series": (1, 3)}
    assert manifest.elements == ["title", "chart-plot", "chart-mark", "chart-label", "chart-legend", "figure", "figure-source"]
    assert manifest.label.strip()
    assert sorted(components.load_manifests()) == ["body", "bullets", "callout", "statement"]


def test_D2_chooser_routes_chart_and_existing_intents():
    route = chooser.load_chooser(manifests=_manifests())
    assert route.choose(_section(), "slides", 0, 1) == "chart"
    assert route.choose(Section(id="s", intent="chart"), "slides", 0, 1) == "bullets"
    for fmt, section, expected in [
        ("slides", Section(id="a", intent="statement", title="Claim"), "statement"),
        ("slides", Section(id="b", intent="bullets", items=[Item(body="Point")] * 3), "bullets"),
        ("doc", Section(id="c", intent="body", paragraphs=["Text"]), "body"),
        ("doc", Section(id="d", intent="callout", items=[Item(body="Point")]), "callout"),
    ]:
        assert route.choose(section, fmt, 0, 1) == expected


def test_D3_fixture_page_and_roles(tmp_path):
    section = _fixture()
    facts = _render(section, tmp_path)
    assert len(facts.pages) == 1
    assert (facts.pages[0].width, facts.pages[0].height) == (960, 540)
    assert any(isinstance(m, marks.SectionMark) and m.id == section.id and m.edge == "start" for m in facts.marks)
    roles = {m.role for m in facts.marks if isinstance(m, marks.ElementMark) and m.id == section.id}
    expected = {"chart-plot", "chart-mark", "chart-label", "figure"}
    if section.title:
        expected.add("title")
    if section.source_line:
        expected.add("figure-source")
    if len(section.data["series"]) >= 2:
        expected.add("chart-legend")
    assert expected <= roles


def test_D4_capacity_fit_marks(tmp_path):
    within = _render(_section(6, 3), tmp_path / "within")
    beyond = _render(_section(7, 3), tmp_path / "beyond")
    good = [m for m in within.marks if isinstance(m, marks.FitMark)]
    bad = [m for m in beyond.marks if isinstance(m, marks.FitMark)]
    assert good and all(m.ok for m in good)
    assert bad and any(not m.ok for m in bad)


def test_D5_check_fixture_deck(tmp_path, capsys):
    section = _fixture()
    source = tmp_path / "deck.md"
    source.write_text(serialise(_doc(section)))
    try:
        code = cli.main(["check", str(source), "--out", str(tmp_path / "out")])
    except SystemExit as error:
        code = error.code
    output = capsys.readouterr()
    assert code == 0, output.out + output.err
    assert "no findings" in output.out.lower()


def test_D6_chart_source_has_no_colour_literals():
    path = ROOT / "src/docla/render/library/chart.typ"
    assert path.is_file(), "chart.typ must exist"
    assert not re.search(r'\b(?:rgb|luma|cmyk)\s*\(|#[0-9a-fA-F]{6}\b', path.read_text())


@pytest.mark.parametrize("chart_type,dimension", [("bar", "w"), ("column", "h")])
def test_D7_mark_lengths_are_proportional(tmp_path, chart_type, dimension):
    facts = _render(_section(chart_type=chart_type), tmp_path)
    lengths = sorted(getattr(m, dimension) for m in facts.marks
                     if isinstance(m, marks.ElementMark) and m.role == "chart-mark")
    assert len(lengths) == 3
    assert lengths[0] > 0
    assert abs(lengths[1] - 2 * lengths[0]) <= 0.5
    assert abs(lengths[2] - 4 * lengths[0]) <= 0.5


def test_D7_unknown_chart_type_notice(tmp_path):
    facts = _render(_section(chart_type="unknown"), tmp_path)
    assert "chart type not supported" in " ".join(word.text for word in facts.words).lower()


def test_D8_figure_fit_measures_chart_height(tmp_path):
    def figure_need(count, folder):
        facts = _render(_section(count, 2), folder)
        figures = [m for m in facts.marks if isinstance(m, marks.FitMark) and m.role == "figure"]
        assert len(figures) == 1
        return figures[0].need

    short = figure_need(2, tmp_path / "short")
    tall = figure_need(6, tmp_path / "tall")
    assert short > 0
    assert tall > short
