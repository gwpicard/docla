# Intent: the docla data models validate Document, Patch, Rule and Finding input and export stable JSON Schemas.
import contextlib
import json
from pathlib import Path

import pytest
try:
    import docla.model as model
except ImportError as error:
    if error.name != "docla.model" and not str(error.name).startswith("docla.model."):
        raise
    model = None

try:
    from docla.model import schema as schema_mod
except ImportError as error:
    if error.name != "docla.model" and not str(error.name).startswith("docla.model."):
        raise
    schema_mod = None



class _Raised:
    value = None


@contextlib.contextmanager
def _validation_error():
    """Expect pydantic's ValidationError (matched by name so collection works before pydantic is installed)."""
    info = _Raised()
    try:
        yield info
    except Exception as exc:
        assert any(c.__name__ == "ValidationError" for c in type(exc).__mro__), repr(exc)
        info.value = exc
    else:
        pytest.fail("expected a ValidationError")


REPO = Path(__file__).resolve().parents[2]
SCHEMA_NAMES = ["Document", "Finding", "Patch", "Rule"]


def _need(name):
    assert model is not None and hasattr(model, name), f"docla.model.{name} must exist"
    return getattr(model, name)


def _error_fields(exc_info):
    return {part for err in exc_info.value.errors() for part in err["loc"]}


def _rule_data(**overrides):
    data = {
        "id": "r-1",
        "title": "Titles fit",
        "origin": "measured",
        "strength": "soft",
        "status": "active",
        "severity": "warning",
        "tier": "geometry",
        "scope": {},
        "check": {"kind": "fits"},
        "remedy": {"class": "tune", "hint": "shrink"},
        "provenance": {"source": None, "created": "2026-01-01", "by": "me"},
        "stats": {},
    }
    data.update(overrides)
    return data


def test_D1_section_requires_intent_only():
    Section = _need("Section")
    section = Section(intent="Explain the plan")
    assert section.intent == "Explain the plan"
    with _validation_error() as info:
        Section()
    assert _error_fields(info) == {"intent"}


def test_D1_document_requires_front_format_sections_and_rev_defaults_to_zero():
    Document = _need("Document")
    doc = Document(front={"title": "T"}, format="slides", sections=[])
    assert doc.rev == 0
    assert doc.format == "slides"
    assert doc.front == {"title": "T"}
    assert Document(front={}, format="doc", sections=[]).format == "doc"
    with _validation_error() as info:
        Document()
    assert _error_fields(info) == {"front", "format", "sections"}


def test_D1_document_rejects_unknown_format():
    Document = _need("Document")
    with _validation_error() as info:
        Document(front={}, format="poster", sections=[])
    assert "format" in _error_fields(info)


def test_D2_patch_requires_base_rev_author_reason_ops():
    Patch = _need("Patch")
    with _validation_error() as info:
        Patch()
    assert _error_fields(info) == {"base_rev", "author", "reason", "ops"}


def test_D2_patch_accepts_each_author_and_rejects_others():
    Patch = _need("Patch")
    for author in ("ai", "human", "system"):
        patch = Patch(base_rev=3, author=author, reason="why", ops=[])
        assert patch.author == author
        assert patch.base_rev == 3
        assert patch.finding_ids == []
    with _validation_error() as info:
        Patch(base_rev=0, author="robot", reason="why", ops=[])
    assert "author" in _error_fields(info)


@pytest.mark.parametrize(
    "op", ["replace_section", "set_fields", "insert_after", "delete_section", "set_attr", "move_section"]
)
def test_D2_patch_op_accepts_each_known_op(op):
    Patch = _need("Patch")
    try:
        patch = Patch(base_rev=0, author="ai", reason="r", ops=[{"op": op}])
    except Exception as exc:
        assert type(exc).__name__ == "ValidationError", repr(exc)
        # other op fields are unspecified here; only the op discriminator must be accepted
        assert not any(e["loc"][-1] == "op" and e["type"] != "missing" for e in exc.errors())
    else:
        assert patch.ops[0].op == op


def test_D2_patch_op_rejects_unknown_op():
    Patch = _need("Patch")
    with _validation_error() as info:
        Patch(base_rev=0, author="ai", reason="r", ops=[{"op": "explode"}])
    assert any("op" in e["loc"] and e["type"] != "missing" for e in info.value.errors())


def _finding_kwargs(**overrides):
    data = {"tier": "geometry", "severity": "error", "format": "slides"}
    data.update(overrides)
    return data


def _try_finding(**overrides):
    """Build a Finding; return (finding, set of fields rejected for a non-missing reason)."""
    Finding = _need("Finding")
    try:
        return Finding(**_finding_kwargs(**overrides)), set()
    except Exception as exc:
        assert type(exc).__name__ == "ValidationError", repr(exc)
        return None, {e["loc"][-1] for e in exc.errors() if e["type"] != "missing"}


@pytest.mark.parametrize("tier", ["source", "geometry", "pixel", "semantic"])
def test_D3_finding_accepts_each_tier(tier):
    finding, rejected = _try_finding(tier=tier)
    assert "tier" not in rejected
    if finding is not None:
        assert finding.tier == tier


@pytest.mark.parametrize("severity", ["error", "warning", "info"])
def test_D3_finding_accepts_each_severity(severity):
    finding, rejected = _try_finding(severity=severity)
    assert "severity" not in rejected
    if finding is not None:
        assert finding.severity == severity


@pytest.mark.parametrize("fmt", ["slides", "doc"])
def test_D3_finding_carries_format(fmt):
    finding, rejected = _try_finding(format=fmt)
    assert "format" not in rejected
    if finding is not None:
        assert finding.format == fmt


@pytest.mark.parametrize(
    "field,value", [("tier", "vibes"), ("severity", "fatal"), ("format", "poster")]
)
def test_D3_finding_rejects_other_values(field, value):
    finding, rejected = _try_finding(**{field: value})
    assert finding is None
    assert field in rejected


def test_D3_finding_requires_format():
    Finding = _need("Finding")
    data = _finding_kwargs()
    del data["format"]
    with _validation_error() as info:
        Finding(**data)
    assert "format" in _error_fields(info)


def test_D4_rule_without_provenance_is_rejected():
    Rule = _need("Rule")
    data = _rule_data()
    del data["provenance"]
    with _validation_error() as info:
        Rule(**data)
    assert "provenance" in _error_fields(info)


def test_D4_hard_measured_rule_is_rejected():
    Rule = _need("Rule")
    with _validation_error() as info:
        Rule(**_rule_data(strength="hard", origin="measured"))
    assert info.value is not None


def test_D4_soft_measured_rule_is_accepted():
    Rule = _need("Rule")
    rule = Rule(**_rule_data(strength="soft", origin="measured"))
    assert rule.strength == "soft"
    assert rule.origin == "measured"
    assert rule.id == "r-1"


def test_D4_rule_status_defaults_to_proposed():
    Rule = _need("Rule")
    data = _rule_data()
    del data["status"]
    assert Rule(**data).status == "proposed"


def test_D5_export_schemas_writes_four_files_deterministically(tmp_path):
    assert schema_mod is not None and hasattr(schema_mod, "export_schemas"), "export_schemas must exist"
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    paths = schema_mod.export_schemas(first)
    again = schema_mod.export_schemas(second)
    expected = [first / f"{name}.schema.json" for name in SCHEMA_NAMES]
    assert paths == sorted(expected)
    assert [p.name for p in again] == [f"{n}.schema.json" for n in SCHEMA_NAMES]
    for p, q in zip(paths, again):
        raw = p.read_bytes()
        assert raw == q.read_bytes()
        assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
        assert b"\r" not in raw
        text = raw.decode("utf-8")
        parsed = json.loads(text)
        assert text == json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    # re-running over existing files leaves identical bytes
    before = {p.name: p.read_bytes() for p in first.iterdir()}
    schema_mod.export_schemas(first)
    assert {p.name: p.read_bytes() for p in first.iterdir()} == before
    assert sorted(before) == [f"{n}.schema.json" for n in SCHEMA_NAMES]


def test_D6_committed_schemas_equal_fresh_export(tmp_path):
    assert schema_mod is not None and hasattr(schema_mod, "export_schemas"), "export_schemas must exist"
    schema_mod.export_schemas(tmp_path)
    committed = REPO / "docs" / "schemas"
    fresh = sorted(p.name for p in tmp_path.iterdir())
    assert fresh == [f"{n}.schema.json" for n in SCHEMA_NAMES]
    assert sorted(p.name for p in committed.glob("*.schema.json")) == fresh
    for name in fresh:
        assert (committed / name).read_bytes() == (tmp_path / name).read_bytes(), name
