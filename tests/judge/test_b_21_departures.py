# Intent: Brand source departures require approval and remain traceable.
import importlib
import importlib.util
import shutil

import pytest
import yaml

from docla.brand.git import run_git
from docla.brand.workspace import BrandError, init_brand
from docla.theme import NEUTRAL_ROOT, ThemeError, load_theme


def _optional_module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name and (error.name == name or name.startswith(error.name + ".")):
            if importlib.util.find_spec(error.name) is None:
                return None
        raise


departures = _optional_module("docla.brand.departures")
labels = _optional_module("docla.theme.labels")
changes = _optional_module("docla.brand.changes")


def _interfaces(*modules):
    for module, names in modules:
        assert module is not None, f"public module providing {', '.join(names)} must exist"
        for name in names:
            assert hasattr(module, name), f"{module.__name__}.{name} must exist"


def _brand(tmp_path):
    brand = init_brand("acme", tmp_path / ".brand")
    theme = brand / "theme"
    shutil.rmtree(theme)
    shutil.copytree(NEUTRAL_ROOT, theme)
    info = yaml.safe_load((theme / "theme.yaml").read_text())
    info["labelled"] = True
    (theme / "theme.yaml").write_text(yaml.safe_dump(info, sort_keys=False))
    inferred = {"label": "inferred", "source": {"note": "Neutral theme judgement"}}
    provenance = {
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
            "pages.slides": {"label": "answered", "source": {"question": "q-1"}},
            "pages.doc": {
                "label": "measured",
                "source": {
                    "file": "materials/guidelines/book.pdf",
                    "role": "guidelines",
                    "page": 33,
                    "quote": "Margins are 20 mm",
                },
            },
            "spacing.unit": inferred,
            "spacing.scale": inferred,
            "imagery.min_dpi": inferred,
        },
        "rubric": {},
    }
    items = yaml.safe_load((theme / "rubric/visual.yaml").read_text())["items"]
    provenance["rubric"] = {item["id"]: inferred for item in items}
    (theme / "provenance.yaml").write_text(yaml.safe_dump(provenance, sort_keys=False))
    run_git(brand, "add", "-A")
    run_git(brand, "commit", "-m", "Add labelled theme")
    return brand


def _answer():
    return labels.ValueProvenance(label="answered", source=labels.ValueSource(question="q-7"))


def _bytes(brand):
    paths = [brand / "theme" / name for name in ("tokens.yaml", "provenance.yaml", "departures.yaml")]
    return [path.read_bytes() if path.exists() else None for path in paths]


def _require():
    _interfaces(
        (departures, ("Departure", "DepartureNotApproved", "set_token", "load_departures", "check_departures")),
        (labels, ("ValueProvenance", "ValueSource", "token_label")),
    )


def test_D1_unapproved_proposal_preserves_files(tmp_path):
    _require()
    brand = _brand(tmp_path)
    before = _bytes(brand)
    with pytest.raises(departures.DepartureNotApproved) as caught:
        departures.set_token(
            brand, "pages.doc.margin.top", "18mm", provenance=_answer(), reason="The examples use 18 mm"
        )
    proposal = caught.value.proposal
    assert isinstance(proposal, departures.Departure)
    assert (proposal.path, proposal.format, proposal.source_value, proposal.value) == (
        "pages.doc.margin.top",
        "doc",
        "20mm",
        "18mm",
    )
    assert proposal.source.source.page == 33
    assert proposal.approved_by == ""
    assert _bytes(brand) == before
    assert before[2] is None


def test_D2_approved_departure_and_blank_reason(tmp_path):
    _require()
    brand = _brand(tmp_path)
    before = _bytes(brand)
    with pytest.raises(BrandError):
        departures.set_token(brand, "pages.doc.margin.top", "18mm", provenance=_answer(), reason="  ", approved=True)
    assert _bytes(brand) == before
    result = departures.set_token(
        brand,
        "pages.doc.margin.top",
        "18mm",
        provenance=_answer(),
        reason="The examples use 18 mm",
        person="owner",
        approved=True,
    )
    assert isinstance(result, departures.Departure)
    assert (result.id, result.status) == ("dep-001", "active")
    theme = load_theme(brand / "theme")
    assert theme.tokens.pages["doc"].margin.top == pytest.approx(18 * 72 / 25.4, abs=0.01)
    assert labels.token_label(theme, "pages.doc.margin.top").label == "answered"
    assert labels.token_label(theme, "pages.doc.margin.left").label == "measured"
    recorded = departures.load_departures(brand)
    assert recorded == [result]
    assert recorded[0].approved_by == "owner"


def test_D3_non_departures_invalid_path_and_rollback(tmp_path):
    _require()
    brand = _brand(tmp_path)
    assert departures.set_token(brand, "pages.slides.margin.left", 52, provenance=_answer(), reason="Update") is None
    assert load_theme(brand / "theme").tokens.pages["slides"].margin.left == 52
    assert departures.load_departures(brand) == []
    assert departures.set_token(brand, "pages.doc.margin.bottom", "20mm", provenance=_answer(), reason="Same") is None
    assert departures.load_departures(brand) == []
    before = _bytes(brand)
    with pytest.raises(BrandError, match="pages.doc.nonesuch"):
        departures.set_token(brand, "pages.doc.nonesuch", 1, provenance=_answer(), reason="Invalid")
    assert _bytes(brand) == before
    with pytest.raises(ThemeError):
        departures.set_token(brand, "colour.usage.text", ["nonesuch"], provenance=_answer(), reason="Invalid")
    assert _bytes(brand) == before


def test_D4_out_of_sync_departure(tmp_path):
    _require()
    brand = _brand(tmp_path)
    departures.set_token(brand, "pages.doc.margin.top", "18mm", provenance=_answer(), reason="Examples", approved=True)
    assert departures.check_departures(brand) == []
    tokens_path = brand / "theme/tokens.yaml"
    tokens = yaml.safe_load(tokens_path.read_text())
    tokens["pages"]["doc"]["margin"]["top"] = "19mm"
    tokens_path.write_text(yaml.safe_dump(tokens, sort_keys=False))
    messages = departures.check_departures(brand)
    assert len(messages) == 1
    assert "pages.doc.margin.top" in messages[0]


def test_D5_cli_approval_records_change(tmp_path, capsys):
    _require()
    _interfaces((changes, ("change_log",)))
    from docla.cli import main

    brand = _brand(tmp_path)
    args = [
        "brand",
        "set",
        "acme",
        "pages.doc.margin.top",
        "18mm",
        "--reason",
        "Examples use 18 mm",
        "--root",
        str(tmp_path / ".brand"),
    ]
    assert main(args) == 2
    output = capsys.readouterr()
    assert "--approve" in output.out + output.err
    assert changes.change_log(brand) == []
    assert run_git(brand, "branch", "--show-current").strip() == "main"
    assert main([*args, "--approve"]) == 0
    records = changes.change_log(brand)
    assert len(records) == 1
    assert "pages.doc.margin.top" in records[-1].what
    assert records[-1].formats == ["doc"]
    assert len(departures.load_departures(brand)) == 1
    assert run_git(brand, "branch", "--show-current").strip() == "main"
    assert run_git(brand, "status", "--porcelain") == ""
