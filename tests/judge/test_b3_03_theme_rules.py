# Intent: themes carry validated rule files that are applied by docla check.
import importlib.util
import runpy
import shutil
from pathlib import Path

import pytest
import yaml

import docla
from docla import cli
from docla.model import Rule
from docla.theme import ThemeError, load_theme, neutral_theme

if importlib.util.find_spec("docla.theme.rules") is None:
    theme_rules = None
else:
    try:
        import docla.theme.rules as theme_rules
    except ImportError as error:
        if error.name != "docla.theme.rules" and not str(error.name).startswith("docla.theme.rules."):
            raise
        theme_rules = None

ROOT = Path(__file__).resolve().parents[1]
NEUTRAL = Path(docla.__file__).resolve().parent / "themes" / "neutral"
SEEDED = ROOT / "fixtures" / "seeded-defects" / "source.empty-section"


def _loader():
    assert theme_rules is not None and hasattr(theme_rules, "load_theme_rules"), "load_theme_rules must exist"
    return theme_rules.load_theme_rules


def _copy(tmp_path):
    path = tmp_path / "theme"
    shutil.copytree(NEUTRAL, path)
    return path


def _rule(**changes):
    data = {
        "id": "house.no-empty",
        "title": "No empty sections",
        "origin": "manual",
        "strength": "hard",
        "status": "active",
        "severity": "warning",
        "tier": "source",
        "provenance": {"by": "owner"},
        "check": {"kind": "all-of", "checks": [{"kind": "empty-section"}]},
        "remedy": {"class": "redraft", "hint": "Fill the section"},
    }
    data.update(changes)
    return data


def _write(root, relative, data):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data), encoding="utf-8")


def _run(source, root, out, capsys):
    try:
        code = cli.main(["check", str(source), "--theme", str(root), "--out", str(out)])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_loads_rule_and_checks_both_fixture_sides(tmp_path, capsys):
    root = _copy(tmp_path)
    data = _rule()
    _write(root, "rules/authored/house-no-empty.yaml", data)
    assert _loader()(load_theme(root)) == [Rule.model_validate(data)]
    code, out, _ = _run(SEEDED / "fail" / "doc.md", root, tmp_path / "fail-out", capsys)
    assert any(line.startswith("warning house.no-empty ") for line in out.splitlines()), (code, out)
    _, out, _ = _run(SEEDED / "pass" / "doc.md", root, tmp_path / "pass-out", capsys)
    assert all("house.no-empty" not in line for line in out.splitlines()), out


def test_D1_rule_order_and_default_status(tmp_path):
    root = _copy(tmp_path)
    _write(root, "rules/learned/z.yaml", _rule(id="house.learned", origin="feedback"))
    _write(root, "rules/authored/z.yaml", _rule(id="house.z"))
    _write(root, "rules/authored/a.yaml", _rule(id="house.a"))
    data = _rule(id="house.ingested", origin="ingested")
    del data["status"]
    _write(root, "rules/ingested/b.yaml", data)
    rules = _loader()(load_theme(root))
    assert [rule.id for rule in rules] == ["house.ingested", "house.a", "house.z", "house.learned"]
    assert rules[0].status == "proposed"


@pytest.mark.parametrize("bad, named", [("missing-provenance", None), ("unknown-kind", "no-such-kind")])
def test_D2_refusal_reaches_cli(tmp_path, capsys, bad, named):
    root = _copy(tmp_path)
    data = _rule()
    if bad == "missing-provenance":
        del data["provenance"]
    else:
        data["check"] = {"kind": "no-such-kind"}
    relative = f"rules/authored/{bad}.yaml"
    _write(root, relative, data)
    with pytest.raises(ThemeError) as caught:
        _loader()(load_theme(root))
    assert str(caught.value).startswith(relative)
    if named:
        assert named in str(caught.value)
    code, _, err = _run(SEEDED / "fail" / "doc.md", root, tmp_path / "out", capsys)
    assert code == 2
    assert relative in err


@pytest.mark.parametrize(
    "data, named",
    [
        ("bad: [", None),
        ({"id": "incomplete"}, None),
        (_rule(provenance={}), None),
        (_rule(check={"kind": "all-of", "checks": [{"kind": "no-such-kind"}]}), "no-such-kind"),
        (_rule(check={"kind": "any-of", "checks": [{"kind": "no-such-kind"}]}), "no-such-kind"),
        (_rule(check={"kind": "not", "checks": [{"kind": "no-such-kind"}]}), "no-such-kind"),
    ],
)
def test_D2_invalid_files_name_the_path_and_unknown_kind(tmp_path, data, named):
    root = _copy(tmp_path)
    relative = "rules/authored/invalid.yaml"
    _write(root, relative, data)
    with pytest.raises(ThemeError) as caught:
        _loader()(load_theme(root))
    assert str(caught.value).startswith(relative)
    if named:
        assert named in str(caught.value)


@pytest.mark.parametrize("case", ["origin", "catalogue", "theme"])
def test_D3_origin_and_duplicate_ids_are_refused(tmp_path, case):
    root = _copy(tmp_path)
    relative = "rules/authored/z.yaml"
    if case == "origin":
        data = _rule(origin="ingested")
        named = None
    elif case == "catalogue":
        data = _rule(id="geo.palette")
        named = "geo.palette"
    else:
        data = _rule(id="house.duplicate")
        _write(root, "rules/authored/a.yaml", data)
        named = "house.duplicate"
    _write(root, relative, data)
    with pytest.raises(ThemeError) as caught:
        _loader()(load_theme(root))
    assert str(caught.value).startswith(relative)
    if named:
        assert named in str(caught.value)


def test_D4_neutral_has_no_rules():
    theme = neutral_theme()
    assert _loader()(theme) == []
    assert not (theme.root / "rules").exists()


@pytest.mark.parametrize("judge", ["test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"])
@pytest.mark.parametrize("text_name", ["SLIDES", "DOC"])
def test_D5_clean_documents_still_report_no_findings(tmp_path, capsys, judge, text_name):
    texts = runpy.run_path(str(Path(__file__).parent / judge))
    source = tmp_path / "doc.md"
    source.write_text(texts[text_name], encoding="utf-8")
    code, out, err = _run(source, NEUTRAL, tmp_path / "out", capsys)
    assert code == 0, err
    assert out.splitlines() == ["no findings"]
