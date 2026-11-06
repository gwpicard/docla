# Intent: Theme terminology guides writers and warns about avoided words in section text.
import importlib
import importlib.util
import shutil
from pathlib import Path

import yaml


def _subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not (str(error.name).startswith(name + ".") and importlib.util.find_spec(name)):
            raise
        return None


voice = _subject("docla.theme.voice")
theme_module = _subject("docla.theme")
brief = _subject("docla.theme.brief")
components = _subject("docla.render.components")
catalogue = _subject("docla.checks.catalogue")
source = _subject("docla.checks.source")
engine = _subject("docla.checks.engine")
parser = _subject("docla.source.parser")
model = _subject("docla.model")
cli = _subject("docla.cli")

SEEDED = Path(__file__).resolve().parents[1] / "fixtures" / "seeded-defects"
JUDGES = Path(__file__).resolve().parent


def _need(module, *names):
    assert module is not None, "public module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"
    return module


def _theme_copy(tmp_path, terminology=None, remove=False):
    theme = _need(theme_module, "neutral_theme", "load_theme").neutral_theme()
    folder = tmp_path / "theme"
    shutil.copytree(theme.root, folder)
    path = folder / "voice" / "terminology.yaml"
    if remove:
        path.unlink()
    else:
        data = yaml.safe_load(path.read_text())
        data["terminology"] = terminology
        path.write_text(yaml.safe_dump(data))
    return theme_module.load_theme(folder)


def _card(theme, max_tokens=1500):
    _need(brief, "brief_card")
    manifest = _need(components, "load_manifests").load_manifests()["bullets"]
    return brief.brief_card(
        theme, "slides", "bullets", manifest, _need(catalogue, "m1_rules").m1_rules(), max_tokens=max_tokens
    )


def _rule():
    rules = _need(catalogue, "all_rules").all_rules()
    matches = [rule for rule in rules if rule.id == "source.terminology-drift"]
    assert len(matches) == 1, "source.terminology-drift must be registered once"
    return matches[0]


def _run(path, out, capsys):
    _need(cli, "main")
    try:
        code = cli.main(["check", str(path), "--out", str(out)])
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out.strip()


def test_D1_neutral_and_empty_voice(tmp_path):
    _need(voice, "Voice", "load_voice")
    theme = _need(theme_module, "neutral_theme").neutral_theme()
    loaded = voice.load_voice(theme)
    assert hasattr(loaded, "terminology"), "Voice.terminology must exist"
    assert [(term.preferred, term.avoid) for term in loaded.terminology] == [("customer", ["client"])]
    assert loaded.banned == ["leverage", "synergy", "unlock", "journey"]
    assert voice.Voice().terminology == []
    empty = _theme_copy(tmp_path, remove=True)
    assert voice.load_voice(empty) == voice.Voice()


def test_D2_catalogue_order_and_rule_metadata():
    _need(catalogue, "all_rules", "m1_rules")
    _need(source, "RULES", "M2_RULES")
    assert [r.id for r in source.RULES] == ["source.citations-resolve", "source.empty-section"]
    assert [r.id for r in catalogue.m1_rules()] == [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
    ]
    assert [r.id for r in source.M2_RULES] == ["source.intent-known"]
    prefix = catalogue.m1_rules() + source.M2_RULES
    rules = catalogue.all_rules()
    assert rules[: len(prefix)] == prefix
    rule = _rule()
    assert rules.index(rule) >= len(prefix)
    assert (rule.severity, rule.tier, rule.remedy.class_) == ("warning", "source", "redraft")
    assert (rule.title, rule.origin, rule.strength, rule.status, rule.check) == (
        "Text uses the theme's preferred word for each concept",
        "manual",
        "soft",
        "active",
        {"kind": "terminology-drift"},
    )


def test_D3_seeded_cli_and_engine(tmp_path, capsys):
    _need(parser, "parse")
    _need(engine, "CheckContext", "run_checks")
    theme = _need(theme_module, "neutral_theme").neutral_theme()
    rule = _rule()
    for side in ("fail", "pass"):
        path = SEEDED / "source.terminology-drift" / side / "doc.md"
        assert path.is_file(), f"missing seeded fixture: {path}"
        code, out = _run(path, tmp_path / side, capsys)
        assert code == 0
        if side == "fail":
            assert any(
                line.startswith("warning source.terminology-drift ") and "customer" in line for line in out.splitlines()
            )
        else:
            assert out == "no findings"
        doc, _ = parser.parse(path.read_text())
        findings = engine.run_checks([rule], engine.CheckContext(doc, theme=theme))
        assert len(findings) == (1 if side == "fail" else 0)
        assert engine.run_checks([rule], engine.CheckContext(doc)) == []


def test_D3_matching_fields_boundaries_and_exclusions():
    _need(model, "Document", "Section", "Item", "Source")
    _need(engine, "CheckContext", "run_checks")
    theme = _need(theme_module, "neutral_theme").neutral_theme()
    doc = model.Document(
        front={},
        format="slides",
        sources=[model.Source(key="S1", text="client")],
        sections=[
            model.Section(
                id="one",
                intent="bullets",
                title="CLIENT",
                items=[model.Item(head="client", body="A Client and client", sub=["client"])],
                paragraphs=["client"],
                note="client",
                spoken="client",
                source_line="client",
            ),
            model.Section(
                id="two",
                intent="body",
                title="clients and clientele",
                paragraphs=["clients"],
                note="client",
                spoken="client",
                source_line="client",
            ),
        ],
    )
    findings = engine.run_checks([_rule()], engine.CheckContext(doc, theme=theme))
    assert len(findings) == 3
    assert {f.measured["field"] for f in findings} == {"title", "items", "paragraphs"}
    for finding in findings:
        assert finding.section_id == "one"
        assert finding.measured == {"field": finding.measured["field"], "avoid": ["client"], "preferred": ["customer"]}
        assert "customer" in finding.message and "client" in finding.message


def test_D4_brief_order_trimming_and_sorted_entries(tmp_path):
    theme = _need(theme_module, "neutral_theme").neutral_theme()
    lines = _card(theme).splitlines()
    preferred = "Preferred: customer (not client)"
    assert preferred in lines
    assert next(i for i, line in enumerate(lines) if line.startswith("Banned:")) < lines.index(preferred)
    assert lines.index(preferred) < next(i for i, line in enumerate(lines) if line.startswith("Hard rules"))
    trimmed = _card(theme, 60)
    assert "Preferred:" not in trimmed and len(trimmed) <= 240
    custom = _theme_copy(
        tmp_path,
        [{"preferred": "staff", "avoid": ["personnel", "workforce"]}, {"preferred": "customer", "avoid": ["client"]}],
    )
    assert "Preferred: customer (not client); staff (not personnel, workforce)" in _card(custom).splitlines()


def test_D5_missing_voice_file_omits_voice_lines(tmp_path):
    card = _card(_theme_copy(tmp_path, remove=True))
    assert not any(line.startswith(("Voice:", "Banned:", "Preferred:")) for line in card.splitlines())


def test_D6_clean_documents_and_geometry_regression(tmp_path, capsys):
    for judge in ("test_m1_17_cli_build_check", "test_m2_theme_in_builds"):
        spec = importlib.util.spec_from_file_location(judge, JUDGES / (judge + ".py"))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for kind in ("SLIDES", "DOC"):
            path = tmp_path / (judge + kind + ".md")
            path.write_text(getattr(module, kind))
            code, out = _run(path, tmp_path / (judge + kind), capsys)
            assert (code, out) == (0, "no findings")
    code, out = _run(SEEDED / "geo.text-fits" / "fail" / "doc.md", tmp_path / "geo", capsys)
    assert code == 1
    assert any(line.startswith("error geo.text-fits ") for line in out.splitlines())
