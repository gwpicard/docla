# Intent: distinct problems survive fingerprint deduplication while true duplicates remain collapsed.
import hashlib
import importlib
import importlib.util
import inspect
import subprocess
import sys
import uuid
from pathlib import Path

from docla.facts.layout import LayoutFacts, PlacedWord
from docla.facts.models import FactBox, PageFacts
from docla.model import Document, Provenance, Remedy, Rule, Scope, Section
from docla.render.marks import ElementMark
from docla.theme import neutral_theme


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name == name and importlib.util.find_spec(name) is None:
            return None
        raise


engine = _module("docla.checks.engine")
catalogue = _module("docla.checks.catalogue")
fonts = _module("docla.checks.fonts")
charts = _module("docla.checks.charts")


def _engine():
    assert engine is not None, "docla.checks.engine must exist"
    for name in ("fingerprint", "make_finding", "register", "run_checks", "CheckContext"):
        assert hasattr(engine, name), f"docla.checks.engine.{name} must exist"
    return engine


def _doc():
    return Document(front={}, format="slides", sections=[Section(id="s1", intent="chart")])


def _facts(words=(), marks=()):
    words, marks = list(words), list(marks)
    return LayoutFacts(
        pdf_sha256="0" * 64,
        pages=[PageFacts(page=1, width=960, height=540, words=words, shapes=[])],
        words=words,
        shapes=[],
        marks=marks,
    )


def _rule(module, rule_id):
    assert module is not None and hasattr(module, "RULES"), f"{rule_id} rules must exist"
    rules = [rule for rule in module.RULES if rule.id == rule_id]
    assert len(rules) == 1
    return rules[0]


def test_D1_fingerprint_key_and_legacy_value():
    eng = _engine()
    assert "key" in inspect.signature(eng.fingerprint).parameters
    assert "key" in inspect.signature(eng.make_finding).parameters
    plain = eng.fingerprint("r", "s1", "body", None, None)
    assert plain == eng.fingerprint("r", "s1", "body", None, None, key=None)
    assert plain == hashlib.sha1(b"r|s1|body|-").hexdigest()
    keyed = eng.fingerprint("r", "s1", "body", None, None, key="a")
    assert keyed == hashlib.sha1(b"r|s1|body|-|a").hexdigest()
    assert keyed != eng.fingerprint("r", "s1", "body", None, None, key="b")


def test_D2_keyed_and_unkeyed_deduplication():
    eng = _engine()
    assert "key" in inspect.signature(eng.make_finding).parameters
    kind = "judge-distinct-" + uuid.uuid4().hex

    @eng.register(kind)
    class Check:
        tier = "source"

        def run(self, ctx, rule):
            return [
                eng.make_finding(rule, ctx, message=message, section_id="s1", role="body", **kwargs)
                for message, kwargs in [
                    ("first a", {"key": "a"}),
                    ("b", {"key": "b"}),
                    ("second a", {"key": "a"}),
                    ("unkeyed first", {"measured": {"n": 1}}),
                    ("unkeyed second", {"measured": {"n": 2}}),
                ]
            ]

    rule = Rule(
        id="judge.distinct",
        title="distinct",
        origin="manual",
        strength="soft",
        status="active",
        severity="warning",
        tier="source",
        scope=Scope(),
        check={"kind": kind},
        remedy=Remedy(**{"class": "tune", "hint": "fix"}),
        provenance=Provenance(),
    )
    findings = eng.run_checks([rule], eng.CheckContext(doc=_doc()))
    assert [f.message for f in findings] == ["first a", "b", "unkeyed first"]
    assert findings[0].fingerprint != findings[1].fingerprint
    assert findings[0].id != findings[1].id
    for finding in findings:
        assert finding.id == hashlib.sha1(f"judge.distinct|s1|{finding.fingerprint}".encode()).hexdigest()[:12]
    assert findings[2].measured == {"n": 1}


def test_D3_outline_order_and_repeat_both_survive():
    eng = _engine()
    assert catalogue is not None and hasattr(catalogue, "document_rules")
    names = ["opener", "ask"] + ["content"] * 17
    doc = Document(
        front={"doctype": "pitch-deck"},
        format="slides",
        sections=[Section(id=f"s{i}", intent="statement", section=name) for i, name in enumerate(names)],
    )
    findings = eng.run_checks(catalogue.document_rules(), eng.CheckContext(doc=doc))
    findings = [f for f in findings if f.rule_id == "source.outline-conforms"]
    assert [f.measured for f in findings] == [
        {"kind": "order", "section": "content"},
        {"kind": "repeat", "section": "content"},
    ]
    assert [f.section_id for f in findings] == ["s2", "s2"]
    assert findings[0].fingerprint != findings[1].fingerprint


def test_D4_font_families_distinct_but_styles_deduplicated():
    eng = _engine()
    rule = _rule(fonts, "geo.fonts")

    def run(names):
        words = [
            PlacedWord(
                text="Word",
                font=name,
                size=24,
                colour="#1A1A1A",
                box=FactBox(page=1, x0=x, y0=100, x1=x + 30, y1=120),
                baseline=118,
                role=None,
                section_id="s1",
            )
            for x, name in zip((10, 50), names, strict=True)
        ]
        return eng.run_checks([rule], eng.CheckContext(doc=_doc(), facts=_facts(words), theme=neutral_theme()))

    findings = run(["ABCDEF+Helvetica-Bold", "ABCDEF+Courier-Regular"])
    assert [f.measured["font"] for f in findings] == ["Helvetica", "Courier"]
    findings = run(["ABCDEF+Helvetica-Bold", "ABCDEF+Helvetica-Regular"])
    assert [f.measured["font"] for f in findings] == ["Helvetica"]


def test_D5_chart_labels_in_same_cell_are_distinct():
    eng = _engine()
    rule = _rule(charts, "geo.chart-labels")
    marks = [
        ElementMark(kind="element", id="s1", role=role, page=1, x=x, y=y, w=20, h=10)
        for role, x, y in [
            ("chart-mark", 800, 450),
            ("chart-mark", 850, 450),
            ("chart-label", 10, 10),
            ("chart-label", 40, 10),
        ]
    ]
    findings = eng.run_checks([rule], eng.CheckContext(doc=_doc(), facts=_facts(marks=marks)))
    assert [f.measured["label"] for f in findings] == [0, 1]
    assert findings[0].fingerprint != findings[1].fingerprint


def test_D6_frozen_judges_pass():
    root = Path(__file__).resolve().parents[2]
    files = [
        "test_m1_11_rule_engine.py",
        "test_b3_10_outline_conforms.py",
        "test_b3_13_fonts.py",
        "test_b3_17_chart_labels.py",
        "test_m4_05_critic.py",
    ]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *[str(root / "tests" / "judge" / f) for f in files]],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
