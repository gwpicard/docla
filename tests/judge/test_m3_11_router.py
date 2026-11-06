# The micro-loop routes findings and selects deterministic component alternatives.
import importlib.util
from dataclasses import dataclass

import pytest

from docla.checks import assets, bounds, fit, gaps, palette
from docla.checks.engine import CheckContext, make_finding
from docla.model import Document, Item, Remedy, Section
from docla.render.chooser import ChooserError, load_chooser

try:
    if importlib.util.find_spec("docla.loop") is None:
        raise ModuleNotFoundError("No module named 'docla.loop'", name="docla.loop")
    import docla.loop.router as router
except ImportError as error:
    if error.name not in ("docla.loop", "docla.loop.router"):
        raise
    router = None


def section(intent="key-numbers", count=3, **kwargs):
    return Section(id="s1", intent=intent, items=[Item(body=f"Item {i}") for i in range(count)], **kwargs)


def finding(rule):
    ctx = CheckContext(doc=Document(front={}, format="slides", sections=[]))
    return make_finding(rule, ctx, message="Finding", section_id="s1")


def rule(rules, rule_id):
    return next(r for r in rules if r.id == rule_id)


def interface(*names):
    assert router is not None, "docla.loop.router must exist"
    for name in names:
        assert hasattr(router, name), f"docla.loop.router.{name} must exist"
    return router


def test_D1_packaged_alternates():
    chooser = load_chooser()
    assert hasattr(chooser, "alternates"), "Chooser.alternates must exist"
    cases = [
        (section(count=3), ["bullets"]),
        (section(count=2), []),
        (section("comparison", 2), ["two-column"]),
        (section("comparison", 5), []),
        (section("full-image", 0, image="picture.png"), ["statement"]),
        (section("full-image", 0), []),
        (section("bullets", 3), []),
    ]
    for value, expected in cases:
        assert chooser.alternates(value, "slides", 0, 1) == expected
    with pytest.raises(ChooserError, match="intent 'timeline' has no entries for format 'slides'"):
        chooser.alternates(section("timeline"), "slides", 0, 1)


def test_D2_locks_route_findings():
    route = interface("route").route
    redraft = finding(rule(fit.RULES, "geo.text-fits"))
    restructure = finding(rule(bounds.RULES, "geo.in-safe-area"))
    for value in (section(lock="text"), section(lock="all"), section(owner="human")):
        plan = route([redraft], value)
        assert plan.report == [redraft]
        assert "locked" in plan.notes[redraft.id]
        assert plan.redraft == []
    assert route([redraft], section()).redraft == [redraft]
    for value in (section(), section(lock="text")):
        assert route([restructure], value).restructure == [restructure]
    plan = route([restructure], section(lock="all"))
    assert plan.report == [restructure]
    assert "locked" in plan.notes[restructure.id]
    assert plan.restructure == []


def test_D3_classes_are_partitioned_and_engine_is_not_actionable():
    module = interface("route", "ACTIONABLE", "Plan")
    tune_rule = rule(bounds.RULES, "geo.in-safe-area").model_copy(
        update={"id": "test.tune", "remedy": Remedy(class_="tune", hint="Adjust")}
    )
    findings = [
        finding(rule(fit.RULES, "geo.text-fits")),
        finding(rule(bounds.RULES, "geo.in-safe-area")),
        finding(tune_rule),
        finding(rule(palette.RULES, "geo.palette")),
        finding(rule(gaps.RULES, "source.gap-present")),
        finding(rule(assets.RULES, "source.image-resolves")),
    ]
    plan = module.route(findings, section())
    assert module.ACTIONABLE == ("redraft", "restructure", "tune")
    for name, expected in zip(("redraft", "restructure", "tune", "engine", "report", "ask"), findings, strict=True):
        assert getattr(plan, name) == [expected]
    assert plan.actionable() == findings[:3]
    assert findings[3] not in plan.actionable()
    second_redraft = make_finding(
        rule(fit.RULES, "geo.text-fits"),
        CheckContext(doc=Document(front={}, format="slides", sections=[])),
        message="Another finding",
        section_id="s1",
        role="title",
    )
    assert module.route([second_redraft, findings[0]], section()).redraft == [second_redraft, findings[0]]
    locked = module.route([findings[2]], section(lock="all"))
    assert locked.report == [findings[2]]
    assert "locked" in locked.notes[findings[2].id]
    assert locked.tune == []
    empty = module.Plan()
    assert empty.actionable() == []
    assert empty.notes == {}


@dataclass
class State:
    section: Section
    findings: list


@dataclass
class Job:
    format: str = "slides"


def test_D4_deterministic_fix_advances_without_mutating():
    fix = interface("deterministic_fix").deterministic_fix
    restructure = finding(rule(bounds.RULES, "geo.in-safe-area"))
    redraft = finding(rule(fit.RULES, "geo.text-fits"))
    original = section(title="Numbers", note="Keep this")
    before = original.model_dump()
    result = fix(State(original, [restructure]), Job())
    assert result is not None
    assert result.component == "bullets"
    assert result.because is not None
    assert "key-figures" in result.because
    assert "geo.in-safe-area" in result.because
    assert result.model_dump(exclude={"component", "because"}) == original.model_dump(exclude={"component", "because"})
    assert original.model_dump() == before
    assert fix(State(section(component="bullets", because="already switched"), [restructure]), Job()) is None
    assert fix(State(section(lock="all"), [restructure]), Job()) is None
    assert fix(State(section(), [redraft]), Job()) is None
    assert fix(State(section("bullets"), [restructure]), Job()) is None


def test_D5_existing_choices_stay_the_same():
    chooser = load_chooser()
    assert chooser.choose(section("statement", 0), "slides", 0, 1) == "statement"
    assert chooser.choose(section("bullets", 3), "slides", 0, 1) == "bullets"
    assert chooser.choose(section("body", 0), "doc", 0, 1) == "body"
    assert chooser.choose(section("callout", 0), "doc", 0, 1) == "callout"
    assert chooser.choose(section("key-numbers", 3), "slides", 0, 1) == "key-figures"
