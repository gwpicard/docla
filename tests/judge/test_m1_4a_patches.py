# Intent: apply_patch changes a Document only through a checked, all-or-nothing patch that enforces the guards.
try:
    from doclo.source import patches
except ImportError as error:
    if error.name not in ("doclo.source", "doclo.source.patches"):
        raise
    patches = None

try:
    import doclo.model as model
except ImportError as error:
    if error.name != "doclo.model" and not str(error.name).startswith("doclo.model."):
        raise
    model = None

import pytest

A, B, C = "a0001", "b0002", "c0003"


def _need():
    assert patches is not None and hasattr(patches, "apply_patch"), "doclo.source.patches.apply_patch must exist"
    assert hasattr(patches, "PatchRejected"), "doclo.source.patches.PatchRejected must exist"
    assert model is not None, "doclo.model must exist"
    return patches.apply_patch


def _doc(**section_overrides):
    """Three sections; overrides map section id to extra Section kwargs."""
    _need()
    def sec(id_, title, **extra):
        kwargs = dict(id=id_, intent=f"intent-{id_}", section=f"line-{id_}", title=title)
        kwargs.update(extra)
        kwargs.update(section_overrides.get(id_, {}))
        return model.Section(**kwargs)

    return model.Document(
        front={"doctype": "pitch-deck"},
        format="slides",
        sections=[sec(A, "Alpha"), sec(B, "Beta"), sec(C, "Gamma")],
        rev=3,
    )


def _op(op, section_id, **kwargs):
    _need()
    return model.PatchOp(op=op, section_id=section_id, **kwargs)


def _patch(*ops, base_rev=3):
    _need()
    return model.Patch(base_rev=base_rev, author="ai", reason="test", ops=list(ops))


def _ids(doc):
    return [s.id for s in doc.sections]


def _rejected(doc, patch, code, **kwargs):
    apply_patch = _need()
    before = doc.model_dump()
    with pytest.raises(patches.PatchRejected) as info:
        apply_patch(doc, patch, **kwargs)
    assert info.value.code == code
    assert doc.model_dump() == before


# D1


def test_D1_stale_base_rev_rejected():
    doc = _doc()
    _rejected(doc, _patch(_op("set_fields", A, fields={"title": "New"}), base_rev=2), "stale-base-rev")


def test_D1_valid_patch_bumps_rev_and_leaves_input():
    apply_patch = _need()
    doc = _doc()
    out = apply_patch(doc, _patch(_op("set_fields", A, fields={"title": "New"})))
    assert out.rev == 4
    assert out.sections[0].title == "New"
    assert doc.rev == 3
    assert doc.sections[0].title == "Alpha"


# D2


def test_D2_set_fields_changes_title_and_items():
    apply_patch = _need()
    out = apply_patch(
        _doc(),
        _patch(_op("set_fields", A, fields={"title": "New", "items": [{"head": "H", "body": "Body"}]})),
    )
    assert out.sections[0].title == "New"
    assert [(i.head, i.body) for i in out.sections[0].items] == [("H", "Body")]
    assert out.sections[1].title == "Beta"


def test_D2_human_owned_section_rejects_text_change():
    doc = _doc(**{A: {"owner": "human"}})
    _rejected(doc, _patch(_op("set_fields", A, fields={"title": "New"})), "owner-locked")


def test_D2_text_lock_rejects_text_change():
    doc = _doc(**{A: {"lock": "text"}})
    _rejected(doc, _patch(_op("set_fields", A, fields={"items": [{"body": "x"}]})), "owner-locked")


def test_D2_human_owned_section_accepts_span():
    apply_patch = _need()
    doc = _doc(**{A: {"owner": "human"}})
    out = apply_patch(doc, _patch(_op("set_fields", A, fields={"span": "full"})))
    assert out.sections[0].span == "full"
    assert out.sections[0].title == "Alpha"
    assert out.rev == 4


# D3


@pytest.mark.parametrize(
    "make_op",
    [
        lambda: _op("set_fields", A, fields={"component": "key-figures"}),
        lambda: _op("set_attr", A, fields={"name": "component", "value": "key-figures"}),
        lambda: _op("delete_section", A),
        lambda: _op("move_section", A, after_id=C),
    ],
    ids=["set_fields-component", "set_attr-component", "delete", "move"],
)
def test_D3_lock_all_rejects(make_op):
    _need()
    doc = _doc(**{A: {"lock": "all"}})
    _rejected(doc, _patch(make_op()), "lock-all")


# D4


def test_D4_set_fields_identity_changes_rejected():
    for field, value in [("id", "zzzzz"), ("intent", "other"), ("section", "other-line")]:
        _rejected(_doc(), _patch(_op("set_fields", A, fields={field: value})), "identity-changed")


def test_D4_replace_section_identity_changes_rejected():
    _need()
    for field, value in [("id", "zzzzz"), ("intent", "other"), ("section", "other-line")]:
        kwargs = dict(id=A, intent=f"intent-{A}", section=f"line-{A}", title="New")
        kwargs[field] = value
        _rejected(_doc(), _patch(_op("replace_section", A, value=model.Section(**kwargs))), "identity-changed")


def test_D4_replace_section_with_same_identity_accepted():
    apply_patch = _need()
    value = model.Section(id=A, intent=f"intent-{A}", section=f"line-{A}", title="Replaced", paragraphs=["p"])
    out = apply_patch(_doc(), _patch(_op("replace_section", A, value=value)))
    assert out.sections[0].title == "Replaced"
    assert out.sections[0].paragraphs == ["p"]
    assert _ids(out) == [A, B, C]


# D5


@pytest.mark.parametrize("name", ["color", "font", "size", "x", "y"])
def test_D5_appearance_forbidden_set_attr(name):
    _rejected(_doc(), _patch(_op("set_attr", A, fields={"name": name, "value": "1"})), "appearance-forbidden")


@pytest.mark.parametrize("name", ["color", "font", "size", "x", "y"])
def test_D5_appearance_forbidden_set_fields(name):
    _rejected(_doc(), _patch(_op("set_fields", A, fields={name: "1"})), "appearance-forbidden")


def test_D5_fact_guard_false_rejects_true_accepts():
    apply_patch = _need()
    doc = _doc()
    patch = _patch(_op("set_fields", A, fields={"title": "New"}))
    _rejected(doc, patch, "fact-unsupported", fact_guard=lambda d, s: False)
    out = apply_patch(doc, patch, fact_guard=lambda d, s: True)
    assert out.sections[0].title == "New"


def test_D5_invalid_resulting_section_rejected():
    _rejected(_doc(), _patch(_op("set_fields", A, fields={"span": "bogus"})), "invalid-section")


def test_D5_component_needs_because():
    _rejected(
        _doc(),
        _patch(_op("set_attr", A, fields={"name": "component", "value": "key-figures"})),
        "invalid-section",
    )


def test_D5_component_accepted_with_because():
    apply_patch = _need()
    set_attr = _op("set_attr", A, fields={"name": "component", "value": "key-figures"})
    out = apply_patch(_doc(**{A: {"because": "numbers lead"}}), _patch(set_attr))
    assert out.sections[0].component == "key-figures"
    out = apply_patch(
        _doc(),
        _patch(_op("set_attr", A, fields={"name": "because", "value": "numbers lead"}), set_attr),
    )
    assert (out.sections[0].component, out.sections[0].because) == ("key-figures", "numbers lead")


# D6


def test_D6_insert_after_places_section():
    apply_patch = _need()
    new = model.Section(id="n0004", intent="new-intent", title="New")
    out = apply_patch(_doc(), _patch(_op("insert_after", A, value=new, after_id=A)))
    assert _ids(out) == [A, "n0004", B, C]
    assert out.sections[1].title == "New"


def test_D6_insert_existing_id_rejected():
    _need()
    dup = model.Section(id=B, intent="new-intent")
    _rejected(_doc(), _patch(_op("insert_after", A, value=dup, after_id=A)), "identity-changed")


def test_D6_delete_removes_section():
    apply_patch = _need()
    out = apply_patch(_doc(), _patch(_op("delete_section", B)))
    assert _ids(out) == [A, C]


def test_D6_move_section_moves_after_target():
    apply_patch = _need()
    out = apply_patch(_doc(), _patch(_op("move_section", A, after_id=C)))
    assert _ids(out) == [B, C, A]
    out = apply_patch(_doc(), _patch(_op("move_section", C, after_id=A)))
    assert _ids(out) == [A, C, B]


def test_D6_unknown_section_rejected():
    _rejected(_doc(), _patch(_op("delete_section", "nope0")), "unknown-section")
    _rejected(_doc(), _patch(_op("set_fields", "nope0", fields={"title": "x"})), "unknown-section")


def test_D6_failing_second_op_leaves_document_unchanged():
    doc = _doc()
    patch = _patch(
        _op("set_fields", A, fields={"title": "New"}),
        _op("delete_section", "nope0"),
    )
    _rejected(doc, patch, "unknown-section")
    assert doc.sections[0].title == "Alpha"
    assert doc.rev == 3
