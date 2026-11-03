# Intent: tests replay recorded Claude responses and a person can record new ones on demand.
import json

import pytest

try:
    from doclo.agents import cassette
except ImportError as error:
    if error.name not in ("doclo.agents", "doclo.agents.cassette"):
        raise
    cassette = None

REQUEST = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
KEY = "6d139f1403cd84518768857efed6c375c0e3fe1af3f250cd3a5c59ea87a0323c"
RESPONSE = {"content": "hello", "n": 1}


def _need():
    assert cassette is not None and hasattr(cassette, "Cassette"), "doclo.agents.cassette.Cassette must exist"
    assert hasattr(cassette, "CassetteMiss"), "CassetteMiss must exist"


class Transport:
    def __init__(self, response=None):
        self.response = RESPONSE if response is None else response
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        return self.response


def _failing(request):
    raise AssertionError("transport must not be called")


def test_D1_replay_returns_stored_response_without_transport(tmp_path):
    _need()
    path = tmp_path / "c.json"
    path.write_text(json.dumps({KEY: {"request": REQUEST, "response": RESPONSE}}), encoding="utf-8")
    c = cassette.Cassette(path, "replay", transport=_failing)
    assert c.call(REQUEST) == {"content": "hello", "n": 1}


def test_D1_replay_is_default_mode(tmp_path):
    _need()
    path = tmp_path / "c.json"
    path.write_text(json.dumps({KEY: {"request": REQUEST, "response": RESPONSE}}), encoding="utf-8")
    assert cassette.Cassette(path).call(REQUEST) == {"content": "hello", "n": 1}


def test_D2_replay_miss_raises_with_key_and_hint(tmp_path):
    _need()
    path = tmp_path / "c.json"
    path.write_text("{}\n", encoding="utf-8")
    c = cassette.Cassette(path, "replay", transport=_failing)
    with pytest.raises(cassette.CassetteMiss) as info:
        c.call(REQUEST)
    assert KEY in str(info.value)
    assert "DOCLO_RECORD=1" in str(info.value)
    assert isinstance(info.value, KeyError)


def test_D2_replay_miss_when_file_absent(tmp_path):
    _need()
    c = cassette.Cassette(tmp_path / "none.json", "replay")
    with pytest.raises(cassette.CassetteMiss):
        c.call(REQUEST)


def test_D3_record_calls_transport_once_writes_and_replays(tmp_path):
    _need()
    path = tmp_path / "c.json"
    t = Transport()
    c = cassette.Cassette(path, "record", transport=t)
    assert c.call(REQUEST) == {"content": "hello", "n": 1}
    assert t.calls == [REQUEST]
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == {KEY: {"request": REQUEST, "response": RESPONSE}}
    replayed = cassette.Cassette(path, "replay", transport=_failing)
    assert replayed.call(REQUEST) == {"content": "hello", "n": 1}


def test_D3_record_keeps_other_requests(tmp_path):
    _need()
    path = tmp_path / "c.json"
    other = {"model": "m", "messages": []}
    c = cassette.Cassette(path, "record", transport=Transport())
    c.call(REQUEST)
    c.call(other)
    replayed = cassette.Cassette(path, "replay")
    assert replayed.call(REQUEST) == RESPONSE
    assert replayed.call(other) == RESPONSE
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 2


def test_D4_from_env_records_when_set(tmp_path, monkeypatch):
    _need()
    monkeypatch.setenv("DOCLO_RECORD", "1")
    path = tmp_path / "c.json"
    t = Transport()
    c = cassette.Cassette.from_env(path, transport=t)
    assert c.call(REQUEST) == RESPONSE
    assert t.calls == [REQUEST]
    assert KEY in json.loads(path.read_text(encoding="utf-8"))


def test_D4_from_env_replays_otherwise(tmp_path, monkeypatch):
    _need()
    monkeypatch.delenv("DOCLO_RECORD", raising=False)
    path = tmp_path / "c.json"
    path.write_text(json.dumps({KEY: {"request": REQUEST, "response": RESPONSE}}), encoding="utf-8")
    c = cassette.Cassette.from_env(path, transport=_failing)
    assert c.call(REQUEST) == RESPONSE
    with pytest.raises(cassette.CassetteMiss):
        c.call({"model": "other"})


def test_D4_from_env_replays_when_value_is_not_one(tmp_path, monkeypatch):
    _need()
    monkeypatch.setenv("DOCLO_RECORD", "0")
    c = cassette.Cassette.from_env(tmp_path / "c.json", transport=_failing)
    with pytest.raises(cassette.CassetteMiss):
        c.call(REQUEST)


def test_D5_secrets_redacted_and_ignored_in_key(tmp_path):
    _need()
    path = tmp_path / "c.json"
    secret = dict(REQUEST, api_key="sk-1", authorization="Bearer x", headers={"x-api-key": "sk-1"})
    c = cassette.Cassette(path, "record", transport=Transport())
    c.call(secret)
    text = path.read_text(encoding="utf-8")
    assert "sk-1" not in text and "Bearer x" not in text
    stored = json.loads(text)
    assert list(stored) == [KEY]
    assert stored[KEY]["request"] == dict(
        REQUEST, api_key="[redacted]", authorization="[redacted]", headers="[redacted]"
    )


def test_D5_requests_differing_only_in_secrets_share_key(tmp_path):
    _need()
    path = tmp_path / "c.json"
    cassette.Cassette(path, "record", transport=Transport()).call(dict(REQUEST, api_key="a"))
    replayed = cassette.Cassette(path, "replay", transport=_failing)
    assert replayed.call(dict(REQUEST, api_key="b", headers={"h": "z"})) == RESPONSE
    assert replayed.call(REQUEST) == RESPONSE


def test_D6_recording_twice_is_byte_identical_and_formatted(tmp_path):
    _need()
    path = tmp_path / "c.json"
    c = cassette.Cassette(path, "record", transport=Transport())
    c.call(REQUEST)
    first = path.read_bytes()
    cassette.Cassette(path, "record", transport=Transport()).call(REQUEST)
    assert path.read_bytes() == first
    assert first.endswith(b"\n") and not first.endswith(b"\n\n")
    assert b"\r" not in first
    expected = json.dumps({KEY: {"request": REQUEST, "response": RESPONSE}}, sort_keys=True, indent=2) + "\n"
    assert first.decode("utf-8") == expected
