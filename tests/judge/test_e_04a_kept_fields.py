# Intent: preserve person-owned fields while allowing explicit regeneration of other section text.
import importlib
import importlib.util
import inspect
import json


def _module(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        if importlib.util.find_spec(name) is not None:
            raise
        return None


ownership = _module("docla.source.ownership")
patches = _module("docla.source.patches")
files = _module("docla.source.files")
ids = _module("docla.source.ids")
parser = _module("docla.source.parser")
serialiser = _module("docla.source.serialiser")
model = _module("docla.model")


def _need(module, *names):
    assert module is not None, "public module must exist"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.{name} must exist"
    return module


def _kept_api(module, name):
    func = getattr(_need(module, name), name)
    assert "kept" in inspect.signature(func).parameters, f"{name} must accept kept"
    return func


def _doc(format="slides", section_id="aaaa1", lock=None):
    m = _need(model, "Document", "Section")
    return m.Document(
        front={"doctype": "memo"},
        format=format,
        sections=[
            m.Section(
                id=section_id,
                intent="purpose",
                section="body",
                owner="human",
                lock=lock,
                title="Mine",
                items=[{"body": "Old"}],
                paragraphs=["Old body"],
            )
        ],
        rev=0,
    )


def _patch(field, value, author="ai", section_id="aaaa1"):
    m = _need(model, "Patch", "PatchOp")
    return m.Patch(
        base_rev=0,
        author=author,
        reason="change",
        ops=[m.PatchOp(op="set_fields", section_id=section_id, fields={field: value})],
    )


def _rejected(call, field=None):
    p = _need(patches, "PatchRejected")
    try:
        call()
    except p.PatchRejected as error:
        assert error.code == "owner-locked", f"expected owner-locked, got {error.code}"
        if field is not None:
            assert field in str(error), f"the refusal must name {field}: {error}"
        return
    raise AssertionError("expected PatchRejected owner-locked, but the patch was applied")


def test_D1_person_fields_and_release(tmp_path):
    o = _need(ownership, "person_fields", "release")
    oplog = tmp_path / ".docla" / "oplog.jsonl"
    assert o.person_fields(oplog, "deck.md") == {}
    oplog.parent.mkdir()
    entries = [
        {
            "rev": 1,
            "author": "human",
            "file": "deck.md",
            "ops": [{"op": "set_fields", "section_id": "aaaa1", "fields": {"title": "Mine", "owner": "human"}}],
        },
        {
            "rev": 2,
            "author": "ai",
            "file": "deck.md",
            "ops": [{"op": "set_fields", "section_id": "aaaa1", "fields": {"items": [{"body": "AI"}]}}],
        },
        {
            "rev": 3,
            "author": "human",
            "file": "deck.md",
            "ops": [{"op": "set_fields", "section_id": "aaaa2", "fields": {"paragraphs": ["x"]}}],
        },
        {
            "rev": 4,
            "author": "human",
            "file": "deck.md",
            "ops": [
                {
                    "op": "replace_section",
                    "section_id": "aaaa3",
                    "value": {"id": "aaaa3", "title": "Title", "items": [{"body": "Point"}], "paragraphs": []},
                }
            ],
        },
        {
            "rev": 5,
            "author": "human",
            "file": "other.md",
            "ops": [{"op": "set_fields", "section_id": "aaaa1", "fields": {"note": "other"}}],
        },
    ]
    oplog.write_text("\n".join(json.dumps(e) for e in entries) + "\nnot json\n[]\n", encoding="utf-8")
    result = o.person_fields(oplog, "deck.md")
    assert result == {"aaaa1": {"title"}, "aaaa2": {"paragraphs"}, "aaaa3": {"title", "items"}}
    released = o.release(result, "aaaa1", "title")
    assert released.get("aaaa1", set()) == set()
    assert released["aaaa2"] == {"paragraphs"}
    released["aaaa2"].add("note")
    assert result == {"aaaa1": {"title"}, "aaaa2": {"paragraphs"}, "aaaa3": {"title", "items"}}


def test_D1_insert_tracks_nonempty_fields_and_ignores_other_ops(tmp_path):
    o = _need(ownership, "person_fields")
    oplog = tmp_path / "oplog.jsonl"
    entry = {
        "author": "human",
        "file": "deck.md",
        "ops": [
            {
                "op": "insert_after",
                "section_id": "aaaa1",
                "value": {"id": "bbbb1", "title": "", "items": [], "note": "Note", "code": None, "owner": "human"},
            },
            {"op": "delete_section", "section_id": "bbbb1"},
            {"op": "set_fields", "section_id": "cccc1", "fields": {"owner": "human", "component": "x"}},
        ],
    }
    oplog.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    assert o.person_fields(oplog, "deck.md") == {"bbbb1": {"note"}}


def test_D2_ai_can_change_unkept_items_but_not_kept_fields():
    apply = _kept_api(patches, "apply_patch")
    doc = _doc()
    result = apply(doc, _patch("items", [{"body": "New"}]), kept={"aaaa1": {"title"}})
    section = result.sections[0]
    assert [item.body for item in section.items] == ["New"]
    assert section.title == "Mine" and section.owner == "human"
    _rejected(lambda: apply(doc, _patch("title", "Changed"), kept={"aaaa1": {"title"}}), "title")
    _rejected(lambda: apply(doc, _patch("items", [{"body": "New"}]), kept={"aaaa1": {"title", "items"}}), "items")
    assert doc.sections[0].title == "Mine" and doc.sections[0].items[0].body == "Old"


def test_D2_ai_cannot_transfer_ownership_with_unkept_edit():
    apply = _kept_api(patches, "apply_patch")
    patch = _patch("items", [{"body": "New"}])
    patch.ops[0].fields["owner"] = "ai"
    section = apply(_doc(), patch, kept={"aaaa1": {"title"}}).sections[0]
    assert section.owner == "human"
    assert [item.body for item in section.items] == ["New"]


def test_D3_default_and_explicit_locks_remain():
    apply = _need(patches, "apply_patch").apply_patch
    doc = _doc()
    _rejected(lambda: apply(doc, _patch("items", [{"body": "New"}])))
    result = apply(doc, _patch("title", "Human title", author="human"))
    assert result.sections[0].title == "Human title"
    # An explicit lock keeps refusing ai text changes. Once apply_patch accepts kept, an empty
    # kept must not lift the lock; before then the plain call shows today's rule.
    extra = {"kept": {}} if "kept" in inspect.signature(apply).parameters else {}
    for lock in ("text", "all"):
        _rejected(lambda lock=lock: apply(_doc(lock=lock), _patch("items", [{"body": "New"}]), **extra))


def test_D4_apply_to_file_persists_and_logs(tmp_path):
    apply = _kept_api(files, "apply_to_file")
    _need(ids, "IdStore")
    _need(serialiser, "serialise")
    _need(parser, "parse")
    path = tmp_path / "deck.md"
    path.write_text(serialiser.serialise(_doc()), encoding="utf-8")
    oplog = tmp_path / ".docla" / "oplog.jsonl"
    store = ids.IdStore(tmp_path / ".docla" / "ids.json")
    result = apply(path, _patch("items", [{"body": "New"}]), oplog, store, kept={"aaaa1": {"title"}})
    parsed, findings = parser.parse(path.read_text(encoding="utf-8"))
    assert not findings
    for section in (result.sections[0], parsed.sections[0]):
        assert section.title == "Mine" and section.owner == "human"
        assert [item.body for item in section.items] == ["New"]
    entries = [json.loads(line) for line in oplog.read_text(encoding="utf-8").splitlines()]
    assert len(entries) == 1 and entries[0]["author"] == "ai"


def test_D4_doc_paragraphs_can_change_but_title_cannot():
    apply = _kept_api(patches, "apply_patch")
    doc = _doc(format="doc", section_id="bbbb1")
    kept = {"bbbb1": {"title"}}
    result = apply(doc, _patch("paragraphs", ["New body"], section_id="bbbb1"), kept=kept)
    assert result.sections[0].paragraphs == ["New body"]
    assert result.sections[0].title == "Mine" and result.sections[0].owner == "human"
    _rejected(lambda: apply(doc, _patch("title", "Changed", section_id="bbbb1"), kept=kept), "title")
