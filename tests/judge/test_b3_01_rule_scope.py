# Intent: Rules receive composition and final-build context and filter findings by component and intent.
import importlib
import importlib.util
import inspect
import json
import runpy
from pathlib import Path

import pytest
from pydantic import ValidationError


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        missing = error.name or ""
        if (missing == name or name.startswith(missing + ".")) and importlib.util.find_spec(missing) is None:
            return None
        raise


engine = _module("docla.checks.engine")
compose = _module("docla.render.compose")
model = _module("docla.model")
schema = _module("docla.model.schema")
cli = _module("docla.cli")
catalogue = _module("docla.checks.catalogue")
source = _module("docla.checks.source")
JUDGE = Path(__file__).resolve().parent
ROOT = JUDGE.parents[1]


def _need(module, *names):
    assert module is not None, "public module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"


def _rule(scope=None, **changes):
    _need(model, "Rule")
    data = {
        "id": "judge.b3-01-scope",
        "title": "Scope judge",
        "origin": "manual",
        "strength": "soft",
        "status": "active",
        "severity": "error",
        "tier": "source",
        "scope": scope or {},
        "check": {"kind": "judge.b3-01.sections"},
        "remedy": {"class": "report", "hint": "Inspect"},
        "provenance": {},
    }
    data.update(changes)
    return model.Rule.model_validate(data)


def _doc():
    _need(model, "Document", "Section")
    return model.Document(
        front={},
        format="slides",
        sections=[
            model.Section(id="aaaa1", intent="statement", title="Statement"),
            model.Section(id="aaaa2", intent="bullets", title="Bullets"),
        ],
    )


def _register(monkeypatch, callback):
    _need(engine, "register", "CHECKS")
    monkeypatch.setitem(engine.CHECKS, "judge.b3-01.sections", None)
    del engine.CHECKS["judge.b3-01.sections"]

    @engine.register("judge.b3-01.sections")
    class SectionsCheck:
        tier = "source"

        def run(self, ctx, rule):
            return callback(ctx, rule)


def _run_cli(argv, capsys):
    _need(cli, "main")
    try:
        code = cli.main(argv)
    except SystemExit as error:
        code = error.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_D1_rule_scope_loop_and_validation():
    _need(model, "Scope", "Rule")
    scope = model.Scope()
    assert hasattr(scope, "components") and scope.components is None
    assert hasattr(scope, "intents") and scope.intents is None
    assert hasattr(_rule(), "loop") and _rule().loop == "both"
    rule = _rule({"components": ["bullets"], "intents": ["bullets"]}, loop="macro")
    assert rule.loop == "macro"
    assert rule.scope.components == ["bullets"]
    assert rule.scope.intents == ["bullets"]
    assert model.Rule.model_validate(rule.model_dump(by_alias=True)) == rule
    with pytest.raises(ValidationError):
        _rule(loop="sometimes")


def test_D1_exported_schema_is_current_and_names_fields(tmp_path):
    _need(schema, "export_schemas")
    schema.export_schemas(tmp_path)
    generated = (tmp_path / "Rule.schema.json").read_bytes()
    assert generated == (ROOT / "docs/schemas/Rule.schema.json").read_bytes()
    data = json.loads(generated)
    assert "loop" in data["properties"]
    assert {"components", "intents"} <= data["$defs"]["Scope"]["properties"].keys()


def test_D2_scopes_filter_each_finding(monkeypatch):
    _need(engine, "CheckContext", "run_checks", "make_finding")
    _need(compose, "compose")
    doc = _doc()
    comp = compose.compose(doc)
    assert "composition" in inspect.signature(engine.CheckContext).parameters, "CheckContext must accept composition"
    ctx = engine.CheckContext(doc, composition=comp)
    _register(
        monkeypatch,
        lambda context, rule: [
            engine.make_finding(rule, context, message="section", section_id=section_id)
            for section_id in ("aaaa1", "aaaa2", None, "missing")
        ],
    )

    def ids(scope, context=ctx):
        return [f.section_id for f in engine.run_checks([_rule(scope)], context)]

    assert ids({"components": ["bullets"]}) == ["aaaa2"]
    assert ids({"intents": ["statement"]}) == ["aaaa1"]
    assert ids({"components": ["bullets"], "intents": ["statement"]}) == []
    assert ids({"components": ["bullets"], "intents": ["bullets"]}) == ["aaaa2"]
    assert ids({}) == ["aaaa1", "aaaa2", None, "missing"]
    assert ids({"components": ["bullets"]}, engine.CheckContext(doc)) == []


def test_D3_context_defaults_and_finding_severity_override():
    _need(engine, "CheckContext", "make_finding")
    ctx = engine.CheckContext(_doc())
    assert hasattr(ctx, "composition") and ctx.composition is None
    assert hasattr(ctx, "final") and ctx.final is False
    rule = _rule()
    assert engine.make_finding(rule, ctx, message="override", severity="warning").severity == "warning"
    assert engine.make_finding(rule, ctx, message="default").severity == "error"


def test_D4_check_final_passes_composition_and_final_flag(tmp_path, capsys, monkeypatch):
    _need(cli, "all_rules")
    _need(engine, "CheckContext")
    assert "composition" in inspect.signature(engine.CheckContext).parameters, "CheckContext must accept composition"
    assert "final" in inspect.signature(engine.CheckContext).parameters, "CheckContext must accept final"
    seen = []

    def observe(ctx, rule):
        seen.append(([(s.id, s.component) for s in ctx.composition.sections], ctx.final))
        return []

    _register(monkeypatch, observe)
    monkeypatch.setattr(cli, "all_rules", lambda: [_rule()])
    text = runpy.run_path(str(JUDGE / "test_m1_17_cli_build_check.py"))["SLIDES"]
    path = tmp_path / "deck.md"
    path.write_text(text)
    for flags in (["--final"], []):
        code, out, err = _run_cli(["check", str(path), "--out", str(tmp_path / "out"), *flags], capsys)
        assert (code, out, err) == (0, "no findings\n", "")
    assert seen == [
        ([("aaaa1", "statement"), ("aaaa2", "bullets")], True),
        ([("aaaa1", "statement"), ("aaaa2", "bullets")], False),
    ]


def test_D4_final_with_catalogue_is_clean(tmp_path, capsys):
    text = runpy.run_path(str(JUDGE / "test_m1_17_cli_build_check.py"))["SLIDES"]
    path = tmp_path / "deck.md"
    path.write_text(text)
    code, out, err = _run_cli(["check", str(path), "--out", str(tmp_path / "out"), "--final"], capsys)
    assert (code, out, err) == (0, "no findings\n", "")


def test_D5_catalogue_prefix_stays_in_order():
    _need(catalogue, "m1_rules", "all_rules")
    _need(source, "RULES", "M2_RULES")
    expected = [
        "source.citations-resolve",
        "source.empty-section",
        "geo.text-fits",
        "geo.in-safe-area",
        "geo.min-font",
        "geo.palette",
    ]
    assert [r.id for r in catalogue.m1_rules()] == expected
    assert [r.id for r in source.RULES] == expected[:2]
    assert [r.id for r in source.M2_RULES] == ["source.intent-known"]
    assert [r.id for r in catalogue.all_rules()][:7] == expected + ["source.intent-known"]


def test_D6_clean_slides_and_docs_still_have_no_findings(tmp_path, capsys):
    for judge in ("test_m1_17_cli_build_check.py", "test_m2_theme_in_builds.py"):
        examples = runpy.run_path(str(JUDGE / judge))
        for name in ("SLIDES", "DOC"):
            path = tmp_path / f"{judge}-{name}.md"
            path.write_text(examples[name])
            code, out, err = _run_cli(["check", str(path), "--out", str(tmp_path / "out")], capsys)
            assert (code, out, err) == (0, "no findings\n", "")
