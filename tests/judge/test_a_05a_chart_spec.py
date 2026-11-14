# Resolve chart data into an explainable, format-independent drawing specification.

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

try:
    import docla.render.chart_spec as chart_spec
except ImportError as error:
    if error.name != "docla.render.chart_spec" and not str(error.name).startswith("docla.render.chart_spec."):
        raise
    if importlib.util.find_spec("docla.render.chart_spec") is not None:
        raise
    chart_spec = None


def subject():
    assert chart_spec is not None, "docla.render.chart_spec must exist"
    for name in ("resolve_chart", "format_value", "ChartSpec", "ChartColour"):
        assert hasattr(chart_spec, name), f"chart_spec.{name} must exist"
    return chart_spec


def fixture_data():
    path = Path(__file__).resolve().parents[1] / "fixtures/components/chart.yaml"
    return yaml.safe_load(path.read_text())["data"]


def test_D1_fixture_spec_and_round_trip():
    api = subject()
    spec = api.resolve_chart(fixture_data())
    assert isinstance(spec, api.ChartSpec)
    assert (spec.type, spec.reason, spec.requested, spec.chosen) == (
        "bar", "requested in the section", "bar", "bar"
    )
    assert spec.categories == ["North", "South", "East", "West"]
    assert (spec.scale.min, spec.scale.max, spec.scale.decimals) == (0.0, 8.0, 0)
    assert spec.legend is True
    assert [s.name for s in spec.series] == ["Current", "Previous"]
    assert [s.values for s in spec.series] == [[4.0, 6.0, 8.0, 5.0], [3.0, 5.0, 6.0, 4.0]]
    assert [s.labels for s in spec.series] == [["4", "6", "8", "5"], ["3", "5", "6", "4"]]
    assert [s.colour for s in spec.series] == [
        api.ChartColour(palette="categorical", index=0),
        api.ChartColour(palette="categorical", index=1),
    ]
    encoded = spec.model_dump_json()
    assert api.ChartSpec.model_validate_json(encoded) == spec
    assert re.search(r"#[0-9a-fA-F]{6}", encoded) is None


@pytest.mark.parametrize(
    ("categories", "values", "extra", "expected_type", "reason"),
    [
        (["2022", "2023", "2024"], [1, 2, 3], {}, "column", "time-like categories read left to right"),
        (["Q1", "Q2", "Q3", "Q4"], [1, 2, 3, 4], {}, "column", "time-like categories read left to right"),
        (["Jan 2026", "Feb 2026"], [1, 2], {}, "column", "time-like categories read left to right"),
        (list("ABCDEFG"), [1] * 7, {}, "bar", "7 or more categories need horizontal bars"),
        (["North", "South"], [4, -2], {}, "bar", "negative values read best as bars"),
        (["2022", "2023"], [4, -2], {}, "bar", "negative values read best as bars"),
        (["North", "South"], [1, 2], {"time_series": True}, "column", "declared time series"),
        (["North", "South"], [1, 2], {}, "bar", "categories compared side by side"),
    ],
)
def test_D2_choice_rules(categories, values, extra, expected_type, reason):
    data = {"categories": categories, "series": [{"name": "Values", "values": values}], **extra}
    spec = subject().resolve_chart(data)
    assert (spec.type, spec.chosen, spec.reason, spec.requested) == (expected_type, expected_type, reason, None)


def test_D3_overrides_and_invalid_data():
    api = subject()
    data = {"type": "column", "categories": list("ABCDEFG"), "series": [{"values": [1] * 7}]}
    spec = api.resolve_chart(data)
    assert (spec.type, spec.reason, spec.chosen) == ("column", "requested in the section", "bar")
    data = fixture_data()
    data["type"] = "unknown"
    spec = api.resolve_chart(data)
    assert (spec.type, spec.reason, spec.chosen) == ("unsupported", "requested type unknown cannot be drawn", "bar")
    data = fixture_data()
    data["series"][0]["values"][0] = "n/a"
    spec = api.resolve_chart(data)
    assert spec.type == "unsupported"
    assert "n/a" in spec.reason
    assert spec.chosen is None
    for empty in (None, {}):
        spec = api.resolve_chart(empty)
        assert (spec.type, spec.reason, spec.chosen) == ("unsupported", "no data to draw", None)
    spec = api.resolve_chart({"categories": ["A", "B", "C"], "series": [{"values": [4]}]})
    assert spec.series[0].values == [4.0, 0.0, 0.0]


@pytest.mark.parametrize(
    ("value", "decimals", "unit", "expected"),
    [
        (1234500, 0, "GBP", "£1,234,500"),
        (-1200, 0, "GBP", "-£1,200"),
        (12.5, 1, "%", "12.5%"),
        (0.125, 2, None, "0.13"),
        (12, 1, "kg", "12.0 kg"),
        (980000.5, 2, None, "980,000.50"),
    ],
)
def test_D4_format_value(value, decimals, unit, expected):
    assert subject().format_value(value, decimals, unit) == expected


def test_D4_resolved_labels_use_shared_precision_and_unit():
    spec = subject().resolve_chart({
        "unit": "%", "categories": ["North", "South"],
        "series": [{"values": [12.5, 8]}],
    })
    assert spec.scale.decimals == 1
    assert spec.series[0].labels == ["12.5%", "8.0%"]
