# Intent: section ids are short, stable and never reused, even after a section is deleted.
import json
import random
import re

import pytest

try:
    from docla.source import ids
except ImportError as error:
    if error.name != "docla.source" and not str(error.name).startswith("docla.source."):
        raise
    ids = None

try:
    from docla.model import Document, Section
except ImportError as error:
    if error.name != "docla.model" and not str(error.name).startswith("docla.model."):
        raise
    Document = Section = None

ID_PATTERN = re.compile(r"[0-9a-f]{5}")


def _subject():
    assert ids is not None and hasattr(ids, "IdStore"), "docla.source.ids.IdStore must exist"
    assert hasattr(ids, "IdStoreError") and hasattr(ids, "stamp"), "IdStoreError and stamp must exist"
    return ids


def _doc(section_ids):
    assert Document is not None and Section is not None, "docla.model must exist"
    return Document(
        format="doc",
        front={"doctype": "memo"},
        sections=[Section(id=i, intent=f"intent {n}") for n, i in enumerate(section_ids)],
    )


def test_D1_allocate_returns_five_hex_chars(tmp_path):
    store = _subject().IdStore(tmp_path / "ids.json", rng=random.Random(1))
    seen = [store.allocate() for _ in range(200)]
    assert all(ID_PATTERN.fullmatch(i) for i in seen)
    assert len(set(seen)) == 200


def test_D1_allocate_avoids_existing(tmp_path):
    mod = _subject()
    first = mod.IdStore(tmp_path / "probe.json", rng=random.Random(7)).allocate()
    store = mod.IdStore(tmp_path / "ids.json", rng=random.Random(7))
    got = store.allocate(existing=[first])
    assert ID_PATTERN.fullmatch(got)
    assert got != first


def test_D2_allocate_skips_already_issued_id(tmp_path):
    mod = _subject()
    path = tmp_path / "ids.json"
    earlier = mod.IdStore(path, rng=random.Random(42))
    issued = earlier.allocate()
    earlier.save()
    again = mod.IdStore(path, rng=random.Random(42))
    got = again.allocate()
    assert ID_PATTERN.fullmatch(got)
    assert got != issued


def test_D2_allocate_skips_id_issued_in_same_store(tmp_path):
    store = _subject().IdStore(tmp_path / "ids.json", rng=random.Random(5))
    first = store.allocate()
    replay = _subject().IdStore(tmp_path / "other.json", rng=random.Random(5))
    assert replay.allocate() == first  # same seed draws the same first id
    # a store that already issued `first` must not hand it out again
    assert store.allocate() != first


def test_D3_save_roundtrip_and_format(tmp_path):
    mod = _subject()
    path = tmp_path / "nested" / "deeper" / "ids.json"
    store = mod.IdStore(path, rng=random.Random(3))
    issued = [store.allocate() for _ in range(5)]
    store.save()
    assert path.read_text(encoding="utf-8") == json.dumps({"issued": sorted(issued)}, indent=2) + "\n"
    assert path.read_bytes().count(b"\r") == 0
    reloaded = mod.IdStore(path, rng=random.Random(3))
    replay = mod.IdStore(tmp_path / "x.json", rng=random.Random(3))
    # the reloaded store must not reissue any id drawn before
    assert replay.allocate() == issued[0]
    assert reloaded.allocate() not in issued


def test_D4_missing_file_is_empty_store(tmp_path):
    mod = _subject()
    path = tmp_path / "absent" / "ids.json"
    store = mod.IdStore(path, rng=random.Random(9))
    assert ID_PATTERN.fullmatch(store.allocate())
    assert not path.exists()


@pytest.mark.parametrize(
    "content",
    ["{not json", "", "[]", '{"other": []}', '{"issued": "abcde"}', '{"issued": [1, 2]}'],
)
def test_D4_corrupt_file_raises_with_path(tmp_path, content):
    mod = _subject()
    path = tmp_path / "ids.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(mod.IdStoreError) as info:
        mod.IdStore(path)
    assert str(path) in str(info.value)
    assert path.read_text(encoding="utf-8") == content


def test_D5_stamp_fills_only_missing_ids_in_order(tmp_path):
    mod = _subject()
    store = mod.IdStore(tmp_path / "ids.json", rng=random.Random(11))
    doc = _doc(["abc12", None, "def34", None])
    before = doc.model_copy(deep=True)
    stamped, new_ids = mod.stamp(doc, store)
    assert doc == before
    assert doc.sections[1].id is None and doc.sections[3].id is None
    assert len(new_ids) == 2 and len(set(new_ids)) == 2
    assert all(ID_PATTERN.fullmatch(i) for i in new_ids)
    assert not set(new_ids) & {"abc12", "def34"}
    assert [s.id for s in stamped.sections] == ["abc12", new_ids[0], "def34", new_ids[1]]
    assert [s.intent for s in stamped.sections] == ["intent 0", "intent 1", "intent 2", "intent 3"]


def test_D5_stamp_avoids_ids_already_in_document(tmp_path):
    mod = _subject()
    taken = mod.IdStore(tmp_path / "probe.json", rng=random.Random(13)).allocate()
    store = mod.IdStore(tmp_path / "ids.json", rng=random.Random(13))
    stamped, new_ids = mod.stamp(_doc([taken, None]), store)
    assert new_ids[0] != taken
    assert stamped.sections[0].id == taken


def test_D6_stamp_is_idempotent(tmp_path):
    mod = _subject()
    store = mod.IdStore(tmp_path / "ids.json", rng=random.Random(21))
    once, first_ids = mod.stamp(_doc([None, "abc12", None]), store)
    twice, second_ids = mod.stamp(once, store)
    assert len(first_ids) == 2
    assert second_ids == []
    assert twice == once
