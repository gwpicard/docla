# Intent: the rule engine runs checks for applicable rules in tier order and returns findings with stable fingerprints.
import hashlib
import importlib
import itertools

import pytest

from docla.model import Box, Document, Provenance, Remedy, Rule, Scope, Section


def _optional(module_name: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as error:
        name = str(error.name)
        if name == "docla" or name.startswith(("docla.checks", "docla.facts")):
            return None
        raise


engine = _optional("docla.checks.engine")
layout = _optional("docla.facts.layout")

_counter = itertools.count()


def _require_interface() -> None:
    assert engine is not None, "docla.checks.engine must exist"
    for name in (
        "CheckContext",
        "register",
        "UnknownCheckError",
        "fingerprint",
        "make_finding",
        "run_checks",
        "CHECKS",
    ):
        assert hasattr(engine, name), f"docla.checks.engine.{name} must exist"


def _kind() -> str:
    return f"t-kind-{next(_counter)}"


def _doc(fmt: str = "doc") -> Document:
    return Document(
        front={},
        format=fmt,
        sections=[Section(id="s1", intent="one"), Section(id="s2", intent="two")],
    )


def _rule(rule_id: str, kind: str, *, tier="source", severity="warning", status="active", fmt=None) -> Rule:
    return Rule(
        id=rule_id,
        title=rule_id,
        origin="manual",
        strength="soft",
        status=status,
        severity=severity,
        tier=tier,
        scope=Scope(format=fmt),
        check={"kind": kind},
        remedy=Remedy(**{"class": "tune", "hint": f"fix {rule_id}"}),
        provenance=Provenance(),
    )


def _facts():
    assert layout is not None and hasattr(layout, "LayoutFacts"), "docla.facts.layout.LayoutFacts must exist"
    return layout.LayoutFacts(pdf_sha256="0" * 64, pages=[], words=[], shapes=[], marks=[])


def _register_per_section(kind: str, tier: str, only: tuple[str, ...] | None = None, calls: list | None = None):
    @engine.register(kind)
    class _Check:
        def run(self, ctx, rule):
            if calls is not None:
                calls.append(rule.id)
            return [
                engine.make_finding(rule, ctx, message=f"{rule.id} on {s.id}", section_id=s.id)
                for s in ctx.doc.sections
                if only is None or s.id in only
            ]

    _Check.tier = tier
    return _Check


def test_D1_check_runs_and_findings_copy_rule_fields():
    _require_interface()
    kind = _kind()
    _register_per_section(kind, "source")
    rule = _rule("r-d1", kind, severity="error")
    ctx = engine.CheckContext(doc=_doc("slides"))
    findings = engine.run_checks([rule], ctx)
    assert [f.section_id for f in findings] == ["s1", "s2"]
    for f in findings:
        assert f.rule_id == "r-d1"
        assert f.tier == "source"
        assert f.severity == "error"
        assert f.remedy.hint == "fix r-d1"
        assert f.remedy.class_ == "tune"
        assert f.format == "slides"
        assert len(f.id) == 12
        assert f.fingerprint == engine.fingerprint("r-d1", f.section_id, None, None, None)
    assert findings[0].id != findings[1].id


def test_D1_finding_id_is_sha1_prefix_of_rule_section_fingerprint():
    _require_interface()
    kind = _kind()
    _register_per_section(kind, "source")
    rule = _rule("r-d1b", kind)
    f = engine.run_checks([rule], engine.CheckContext(doc=_doc()))[0]
    expected = hashlib.sha1(f"r-d1b|s1|{f.fingerprint}".encode()).hexdigest()[:12]
    assert f.id == expected


def test_D1_context_defaults():
    _require_interface()
    ctx = engine.CheckContext(doc=_doc())
    assert ctx.facts is None
    assert ctx.tokens == {}


def test_D2_inactive_and_out_of_scope_rules_produce_no_findings():
    _require_interface()
    kind = _kind()
    calls: list[str] = []
    _register_per_section(kind, "source", calls=calls)
    rules = [
        _rule("r-proposed", kind, status="proposed"),
        _rule("r-retired", kind, status="retired"),
        _rule("r-slides", kind, fmt="slides"),
    ]
    assert engine.run_checks(rules, engine.CheckContext(doc=_doc("doc"))) == []
    assert calls == []


def test_D2_probation_and_matching_format_rules_run():
    _require_interface()
    kind = _kind()
    _register_per_section(kind, "source")
    rules = [
        _rule("r-prob", kind, status="probation"),
        _rule("r-doc", kind, fmt="doc"),
    ]
    findings = engine.run_checks(rules, engine.CheckContext(doc=_doc("doc")))
    assert sorted({f.rule_id for f in findings}) == ["r-doc", "r-prob"]
    assert len(findings) == 4


def test_D3_unregistered_kind_raises_naming_kind():
    _require_interface()
    rule = _rule("r-d3", "no-such-kind-xyz")
    with pytest.raises(engine.UnknownCheckError, match="no-such-kind-xyz"):
        engine.run_checks([rule], engine.CheckContext(doc=_doc()))
    assert issubclass(engine.UnknownCheckError, KeyError)


def test_D3_registering_a_kind_twice_raises_value_error():
    _require_interface()
    kind = _kind()
    _register_per_section(kind, "source")
    with pytest.raises(ValueError):
        _register_per_section(kind, "source")


def test_D3_register_stores_an_instance_under_kind():
    _require_interface()
    kind = _kind()
    cls = _register_per_section(kind, "source")
    assert isinstance(engine.CHECKS[kind], cls)


def test_D4_same_eighth_same_fingerprint_different_eighth_differs():
    _require_interface()
    size = (800.0, 800.0)
    a = engine.fingerprint("r", "s1", "body", Box(x=10, y=10, w=20, h=20), size)
    same = engine.fingerprint("r", "s1", "body", Box(x=70, y=70, w=20, h=20), size)
    other_x = engine.fingerprint("r", "s1", "body", Box(x=110, y=10, w=20, h=20), size)
    other_y = engine.fingerprint("r", "s1", "body", Box(x=10, y=110, w=20, h=20), size)
    assert a == same
    assert a != other_x
    assert a != other_y


def test_D4_role_and_section_change_the_fingerprint():
    _require_interface()
    size = (800.0, 800.0)
    box = Box(x=10, y=10, w=20, h=20)
    base = engine.fingerprint("r", "s1", "body", box, size)
    assert engine.fingerprint("r", "s1", "title", box, size) != base
    assert engine.fingerprint("r", "s2", "body", box, size) != base
    assert engine.fingerprint("r2", "s1", "body", box, size) != base


def test_D4_without_region_the_cell_is_a_dash():
    _require_interface()
    expected = hashlib.sha1(b"r|s1|body|-").hexdigest()
    assert engine.fingerprint("r", "s1", "body", None, None) == expected
    assert engine.fingerprint("r", "s1", "body", Box(x=1, y=1, w=1, h=1), None) == expected


def test_D4_measured_values_and_message_never_change_the_fingerprint():
    _require_interface()
    rule = _rule("r-d4", "unused")
    ctx = engine.CheckContext(doc=_doc())
    a = engine.make_finding(rule, ctx, message="too long: 12", section_id="s1", measured={"n": 12})
    b = engine.make_finding(rule, ctx, message="too long: 13", section_id="s1", measured={"n": 13})
    assert a.fingerprint == b.fingerprint
    assert a.id == b.id
    assert a.measured == {"n": 12}
    assert b.message == "too long: 13"


def test_D5_source_error_drops_geometry_findings_for_that_section_only():
    _require_interface()
    src_kind, geo_kind = _kind(), _kind()
    _register_per_section(src_kind, "source", only=("s1",))
    _register_per_section(geo_kind, "geometry")
    rules = [
        _rule("r-geo", geo_kind, tier="geometry"),
        _rule("r-src", src_kind, tier="source", severity="error"),
    ]
    ctx = engine.CheckContext(doc=_doc(), facts=_facts())
    findings = engine.run_checks(rules, ctx)
    assert [(f.rule_id, f.section_id) for f in findings] == [("r-src", "s1"), ("r-geo", "s2")]


def test_D5_source_warning_does_not_drop_geometry_findings():
    _require_interface()
    src_kind, geo_kind = _kind(), _kind()
    _register_per_section(src_kind, "source", only=("s1",))
    _register_per_section(geo_kind, "geometry")
    rules = [
        _rule("r-src", src_kind, tier="source", severity="warning"),
        _rule("r-geo", geo_kind, tier="geometry"),
    ]
    findings = engine.run_checks(rules, engine.CheckContext(doc=_doc(), facts=_facts()))
    assert [(f.rule_id, f.section_id) for f in findings] == [
        ("r-src", "s1"),
        ("r-geo", "s1"),
        ("r-geo", "s2"),
    ]


def test_D5_geometry_is_skipped_without_facts_and_runs_with_them():
    _require_interface()
    kind = _kind()
    calls: list[str] = []
    _register_per_section(kind, "geometry", calls=calls)
    rule = _rule("r-geo-only", kind, tier="geometry")
    assert engine.run_checks([rule], engine.CheckContext(doc=_doc())) == []
    assert calls == []
    assert len(engine.run_checks([rule], engine.CheckContext(doc=_doc(), facts=_facts()))) == 2
    assert calls == ["r-geo-only"]


def test_D5_tiers_run_in_order_regardless_of_rule_order():
    _require_interface()
    order: list[str] = []
    kinds = {tier: _kind() for tier in ("source", "geometry")}
    for tier, kind in kinds.items():
        _register_per_section(kind, tier, calls=order)
    rules = [
        _rule("r-geo", kinds["geometry"], tier="geometry"),
        _rule("r-src", kinds["source"], tier="source"),
    ]
    engine.run_checks(rules, engine.CheckContext(doc=_doc(), facts=_facts()))
    assert order == ["r-src", "r-geo"]


def test_D6_findings_with_the_same_fingerprint_are_returned_once():
    _require_interface()
    kind = _kind()

    @engine.register(kind)
    class _Dup:
        tier = "source"

        def run(self, ctx, rule):
            return [
                engine.make_finding(rule, ctx, message="first", section_id="s1", role="body"),
                engine.make_finding(rule, ctx, message="second", section_id="s1", role="body"),
                engine.make_finding(rule, ctx, message="other", section_id="s2", role="body"),
            ]

    findings = engine.run_checks([_rule("r-d6", kind)], engine.CheckContext(doc=_doc()))
    assert [(f.section_id, f.message) for f in findings] == [("s1", "first"), ("s2", "other")]
