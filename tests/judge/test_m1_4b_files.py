# Intent: apply_to_file applies a patch to a working file atomically and appends one explaining line to the oplog.
import json
import random
import re

import pytest

try:
    from docla.source import files
except ImportError as error:
    if error.name != "docla.source" and not str(error.name).startswith("docla.source."):
        raise
    files = None

try:
    from docla.source import ids as ids_mod
    from docla.source import patches
except ImportError as error:
    if error.name != "docla.source" and not str(error.name).startswith("docla.source."):
        raise
    ids_mod = patches = None

try:
    import docla.model as model
except ImportError as error:
    if error.name != "docla.model" and not str(error.name).startswith("docla.model."):
        raise
    model = None

A = "a7c31"
FRONT = "---\ndoctype: memo\nformat: doc\ntitle: T\n---\n\n"
FENCE_A = f'::: {{#{A} .section intent="first" section="finding"}}\n## Old\n:::\n'
FENCE_B = '::: {.section intent="second" section="finding"}\n## Second\n:::\n'
STAMPED_B = re.compile(r'::: \{#([0-9a-f]{5}) \.section intent="second" section="finding"\}\n## Second\n:::\n')


def _need():
    assert files is not None, "docla.source.files must exist"
    assert hasattr(files, "apply_to_file") and hasattr(files, "current_rev"), "apply_to_file and current_rev must exist"
    assert ids_mod is not None and patches is not None and model is not None, "docla.source ids/patches and docla.model must exist"
    return files


def _patch(base_rev=0, title="New", section_id=A, field="title"):
    _need()
    op = model.PatchOp(op="set_fields", section_id=section_id, fields={field: title})
    return model.Patch(base_rev=base_rev, author="ai", reason="retitle", finding_ids=["f1"], ops=[op])


def _setup(tmp_path, fences=(FENCE_A, FENCE_B), seed=1):
    _need()
    path = tmp_path / "memo.md"
    path.write_bytes((FRONT + "\n".join(fences)).encode())
    oplog = tmp_path / ".docla" / "oplog.jsonl"
    store = ids_mod.IdStore(tmp_path / ".docla" / "ids.json", rng=random.Random(seed))
    return path, oplog, store


def _lines(oplog):
    return [json.loads(line) for line in oplog.read_text().splitlines()]


def test_D1_current_rev_missing_log_is_zero(tmp_path):
    assert _need().current_rev(tmp_path / "nope.jsonl") == 0


def test_D1_current_rev_counts_non_empty_lines(tmp_path):
    log = tmp_path / "oplog.jsonl"
    log.write_text('{"rev": 1}\n{"rev": 2}\n\n{"rev": 3}\n')
    assert _need().current_rev(log) == 3


def test_D2_valid_patch_rewrites_file_and_logs(tmp_path):
    path, oplog, store = _setup(tmp_path)
    doc = _need().apply_to_file(path, _patch(), oplog, store)
    assert doc.rev == 1
    text = path.read_text()
    assert text.startswith(FRONT + FENCE_A.replace("Old", "New") + "\n")
    match = STAMPED_B.search(text)
    assert match, text
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert [s.id for s in doc.sections] == [A, match.group(1)]
    assert doc.sections[0].title == "New"
    entries = _lines(oplog)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["rev"] == 1
    assert entry["author"] == "ai"
    assert entry["reason"] == "retitle"
    assert entry["finding_ids"] == ["f1"]
    assert entry["file"] == "memo.md"
    assert len(entry["ops"]) == 1
    assert entry["ops"][0]["op"] == "set_fields" and entry["ops"][0]["section_id"] == A


def test_D2_stamped_ids_are_saved_in_the_store(tmp_path):
    path, oplog, store = _setup(tmp_path)
    _need().apply_to_file(path, _patch(), oplog, store)
    new_id = STAMPED_B.search(path.read_text()).group(1)
    saved = json.loads((tmp_path / ".docla" / "ids.json").read_text())
    assert new_id in saved["issued"]


def test_D2_log_line_has_sorted_keys(tmp_path):
    path, oplog, store = _setup(tmp_path)
    _need().apply_to_file(path, _patch(), oplog, store)
    keys = list(json.loads(oplog.read_text().splitlines()[0], object_pairs_hook=lambda p: dict(p)))
    assert keys == sorted(keys)
    assert {"rev", "author", "reason", "finding_ids", "ops", "file"} <= set(keys)


def test_D3_second_patch_uses_base_rev_one(tmp_path):
    path, oplog, store = _setup(tmp_path)
    mod = _need()
    mod.apply_to_file(path, _patch(base_rev=0), oplog, store)
    doc = mod.apply_to_file(path, _patch(base_rev=1, title="Newer"), oplog, store)
    assert doc.rev == 2
    assert doc.sections[0].title == "Newer"
    assert [e["rev"] for e in _lines(oplog)] == [1, 2]
    assert mod.current_rev(oplog) == 2


def test_D3_stale_base_rev_rejected_and_nothing_changes(tmp_path):
    path, oplog, store = _setup(tmp_path)
    mod = _need()
    mod.apply_to_file(path, _patch(base_rev=0), oplog, store)
    file_before, log_before = path.read_bytes(), oplog.read_bytes()
    with pytest.raises(patches.PatchRejected) as info:
        mod.apply_to_file(path, _patch(base_rev=0, title="Stale"), oplog, store)
    assert info.value.code == "stale-base-rev"
    assert path.read_bytes() == file_before
    assert oplog.read_bytes() == log_before


def test_D4_rejected_patch_leaves_file_log_and_id_store(tmp_path):
    fences = (FENCE_A.replace("}\n", ' owner="human"}\n', 1), FENCE_B)
    path, oplog, store = _setup(tmp_path, fences)
    ids_path = tmp_path / ".docla" / "ids.json"
    ids_path.parent.mkdir()
    ids_path.write_bytes(b'{\n  "issued": [\n    "00000"\n  ]\n}\n')
    file_before, ids_before = path.read_bytes(), ids_path.read_bytes()
    with pytest.raises(patches.PatchRejected) as info:
        _need().apply_to_file(path, _patch(), oplog, store)
    assert info.value.code == "owner-locked"
    assert path.read_bytes() == file_before
    assert ids_path.read_bytes() == ids_before
    assert not oplog.exists()


def test_D4_rejected_patch_does_not_create_id_store(tmp_path):
    fences = (FENCE_A.replace("}\n", ' lock="text"}\n', 1), FENCE_B)
    path, oplog, store = _setup(tmp_path, fences)
    with pytest.raises(patches.PatchRejected):
        _need().apply_to_file(path, _patch(), oplog, store)
    assert not (tmp_path / ".docla" / "ids.json").exists()
    assert not oplog.exists()


@pytest.mark.parametrize(
    "bad_fence",
    [
        f'::: {{#{A} .section intent="first" section="finding"}}\n## Old\n',
        f'::: {{#{A} .section intent="first" section="finding" color="red"}}\n## Old\n:::\n',
    ],
    ids=["parse-error", "appearance-in-source"],
)
def test_D5_unparseable_file_rejected_and_unchanged(tmp_path, bad_fence):
    path, oplog, store = _setup(tmp_path, (bad_fence,))
    before = path.read_bytes()
    with pytest.raises(patches.PatchRejected) as info:
        _need().apply_to_file(path, _patch(), oplog, store)
    assert info.value.code == "unparseable"
    assert path.read_bytes() == before
    assert not oplog.exists()


def test_D6_no_temporary_file_remains_and_log_is_lf(tmp_path):
    path, oplog, store = _setup(tmp_path)
    mod = _need()
    mod.apply_to_file(path, _patch(base_rev=0), oplog, store)
    mod.apply_to_file(path, _patch(base_rev=1, title="Newer"), oplog, store)
    assert sorted(p.name for p in tmp_path.iterdir()) == [".docla", "memo.md"]
    assert sorted(p.name for p in oplog.parent.iterdir()) == ["ids.json", "oplog.jsonl"]
    raw = oplog.read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert raw.count(b"\n") == 2
    assert b"\r" not in path.read_bytes()
