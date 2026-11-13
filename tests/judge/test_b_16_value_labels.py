# Intent: every labelled theme value has a valid, traceable origin.
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

import docla
from docla.model import Rule
from docla.model.schema import export_schemas
from docla.theme import ThemeError, load_theme, neutral_theme
from docla.theme.rubric import load_rubric
from docla.theme.rules import load_theme_rules

if importlib.util.find_spec("docla.theme.labels") is None:
    labels = None
else:
    try:
        import docla.theme.labels as labels
    except ImportError as error:
        if error.name != "docla.theme.labels" and not str(error.name).startswith("docla.theme.labels."):
            raise
        labels = None

NEUTRAL = Path(docla.__file__).resolve().parent / "themes" / "neutral"
SCHEMA = Path(__file__).resolve().parents[2] / "docs/schemas/Rule.schema.json"


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _fixture(tmp_path, labelled=True):
    root = tmp_path / "theme"
    shutil.copytree(NEUTRAL, root)
    info = yaml.safe_load((root / "theme.yaml").read_text(encoding="utf-8"))
    if labelled:
        info["labelled"] = True
        _write(root / "theme.yaml", info)
    inferred = {"label": "inferred", "source": {"note": "Judged from the brand"}}
    data = {
        "tokens": {
            "colour.roles": {
                "label": "measured",
                "source": {
                    "file": "materials/guidelines/book.pdf",
                    "role": "guidelines",
                    "page": 4,
                    "quote": "Ink #1A1A1A",
                },
            },
            "colour.chart": {"label": "derived", "source": {"from": ["colour.roles.accent", "colour.roles.ink"]}},
            "colour.usage": inferred,
            "colour.contrast_min": inferred,
            "type.families": {"label": "measured", "source": {"file": "materials/fonts/fonts.yaml", "role": "fonts"}},
            "type.scale": {
                "label": "measured",
                "source": {"files": ["materials/examples/a.pdf", "materials/examples/b.pdf"], "role": "examples"},
            },
            "pages.slides": {
                "label": "measured",
                "source": {"file": "materials/templates/deck.pptx", "role": "templates"},
            },
            "pages.doc": {"label": "answered", "source": {"question": "conflict.pages.doc.margin.top"}},
            "spacing.unit": inferred,
            "spacing.scale": inferred,
            "imagery.min_dpi": inferred,
        },
        "rubric": {},
    }
    rubric = yaml.safe_load((root / "rubric/visual.yaml").read_text(encoding="utf-8"))
    data["rubric"] = {item["id"]: inferred for item in rubric["items"]}
    if labelled:
        _write(root / "provenance.yaml", data)
    return root, data


def _rule(source, *, label="measured", strength="soft", status="proposed"):
    provenance = {"source": source}
    if label is not None:
        provenance["label"] = label
    return {
        "id": "house.label-test",
        "title": "A brand rule",
        "origin": "ingested",
        "strength": strength,
        "status": status,
        "severity": "warning",
        "tier": "source",
        "provenance": provenance,
        "check": {"kind": "empty-section"},
        "remedy": {"class": "redraft", "hint": "Fill the section"},
    }


def _labels():
    assert labels is not None, "docla.theme.labels must exist"
    for name in ("token_label", "token_paths", "load_provenance"):
        assert hasattr(labels, name), f"docla.theme.labels.{name} must exist"
    return labels


def test_D1_token_labels_and_raw_paths(tmp_path):
    api = _labels()
    root, _ = _fixture(tmp_path)
    theme = load_theme(root)
    accent = api.token_label(theme, "colour.roles.accent")
    assert (accent.label, accent.source.page) == ("measured", 4)
    margin = api.token_label(theme, "pages.doc.margin.top")
    assert (margin.label, margin.source.question) == ("answered", "conflict.pages.doc.margin.top")
    assert api.token_label(theme, "type.scale.doc.body.size").source.files == [
        "materials/examples/a.pdf",
        "materials/examples/b.pdf",
    ]
    with pytest.raises(KeyError):
        api.token_label(theme, "colour.roles.nonesuch")
    paths = api.token_paths(yaml.safe_load((root / "tokens.yaml").read_text(encoding="utf-8")))
    assert paths == sorted(paths)
    assert {"pages.doc.margin.top", "colour.chart.categorical", "type.scale.slides.min_size"} <= set(paths)
    assert "schema" not in paths


@pytest.mark.parametrize(
    "case,named",
    [
        ("missing", "spacing.unit"),
        ("unknown", "colour.roles.nonesuch"),
        ("short", "colour"),
        ("file", None),
        ("question", None),
        ("note", None),
        ("absent", "provenance.yaml"),
    ],
)
def test_D2_invalid_token_provenance_is_refused(tmp_path, case, named):
    root, data = _fixture(tmp_path)
    tokens = data["tokens"]
    if case == "missing":
        del tokens["spacing.unit"]
    elif case == "unknown":
        tokens["colour.roles.nonesuch"] = tokens["colour.roles"]
    elif case == "short":
        tokens["colour"] = tokens["colour.roles"]
    elif case == "file":
        del tokens["colour.roles"]["source"]["file"]
    elif case == "question":
        del tokens["pages.doc"]["source"]["question"]
    elif case == "note":
        tokens["colour.usage"] = {"label": "inferred", "source": {"note": "  "}}
    if case == "absent":
        (root / "provenance.yaml").unlink()
    else:
        _write(root / "provenance.yaml", data)
    with pytest.raises(ThemeError) as caught:
        load_theme(root)
    if named:
        assert named in str(caught.value)


@pytest.mark.parametrize(
    "source,label,strength,status,valid",
    [
        ({"file": "materials/examples/a.pdf", "role": "examples"}, None, "soft", "proposed", False),
        ({"file": "materials/examples/a.pdf", "role": "examples"}, "measured", "soft", "proposed", True),
        ({"file": "materials/examples/a.pdf", "role": "examples"}, "measured", "hard", "proposed", False),
        ({"file": "materials/examples/a.pdf", "role": "examples"}, "measured", "soft", "active", False),
        ({"file": "materials/templates/deck.pptx", "role": "templates"}, "measured", "hard", "active", True),
        (
            {
                "file": "materials/guidelines/book.pdf",
                "role": "guidelines",
                "page": 12,
                "quote": "Body text is never smaller than 18 pt",
            },
            "measured",
            "hard",
            "active",
            True,
        ),
        (
            {"file": "materials/guidelines/book.pdf", "role": "guidelines", "page": 12},
            "measured",
            "hard",
            "active",
            False,
        ),
    ],
)
def test_D3_rule_label_policy(tmp_path, source, label, strength, status, valid):
    root, _ = _fixture(tmp_path)
    relative = "rules/ingested/brand.yaml"
    _write(root / relative, _rule(source, label=label, strength=strength, status=status))
    theme = load_theme(root)
    if valid:
        rules = load_theme_rules(theme)
        assert len(rules) == 1
        assert hasattr(rules[0].provenance, "label"), "rule provenance must expose label"
        assert (rules[0].provenance.label, rules[0].strength, rules[0].status) == ("measured", strength, status)
    else:
        with pytest.raises(ThemeError) as caught:
            load_theme_rules(theme)
        assert str(caught.value).startswith(relative)


def test_D4_rubric_item_requires_provenance(tmp_path):
    root, data = _fixture(tmp_path)
    item_id = next(iter(data["rubric"]))
    del data["rubric"][item_id]
    _write(root / "provenance.yaml", data)
    with pytest.raises(ThemeError) as caught:
        load_rubric(load_theme(root))
    assert str(caught.value).startswith("rubric/visual.yaml:")
    assert item_id in str(caught.value)


def test_D5_unlabelled_themes_and_rules(tmp_path):
    api = _labels()
    neutral = neutral_theme()
    assert neutral.info.labelled is False
    assert api.load_provenance(neutral).model_dump() == {"tokens": {}, "rubric": {}}
    root, _ = _fixture(tmp_path, labelled=False)
    relative = "rules/ingested/brand.yaml"
    _write(root / relative, _rule({"file": "materials/examples/a.pdf", "role": "examples"}, label=None))
    theme = load_theme(root)
    assert len(load_theme_rules(theme)) == 1
    _write(root / relative, _rule({"file": "materials/examples/a.pdf", "role": "examples"}, label="answered"))
    with pytest.raises(ThemeError) as caught:
        load_theme_rules(theme)
    assert str(caught.value).startswith(relative)


def test_D6_rule_schema_and_export(tmp_path):
    schema = Rule.model_json_schema()
    label = schema["$defs"]["Provenance"]["properties"].get("label")
    assert label is not None, "Rule provenance must expose label in its schema"
    variants = label.get("anyOf", [label])
    assert any(part.get("enum") == ["measured", "derived", "inferred", "answered"] for part in variants)
    export_schemas(tmp_path)
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == json.loads(
        (tmp_path / "Rule.schema.json").read_text(encoding="utf-8")
    )
