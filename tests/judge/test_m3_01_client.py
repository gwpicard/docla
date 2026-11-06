# Intent: Claude validates replies and records usage through a transport.
import ast
import asyncio
import base64
import importlib
import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from pydantic import BaseModel
from docla.agents.cassette import Cassette


def optional(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if error.name != name and not name.startswith(f"{error.name}.") and not str(error.name).startswith(f"{name}."):
            raise
        try:
            spec = importlib.util.find_spec(name)
        except ModuleNotFoundError as missing:
            if not name.startswith(f"{missing.name}."):
                raise
            spec = None
        if spec is not None:
            raise
        return None


client = optional("docla.agents.client")
fakes = optional("docla.testing.fakes")


class Schema(BaseModel):
    title: str


class Ledger:
    def __init__(self):
        self.entries = []

    def add(self, role, model, usage):
        self.entries.append((role, model, usage))


def interfaces():
    assert client is not None, "docla.agents.client must exist"
    assert fakes is not None, "docla.testing.fakes must exist"
    for name in ("Claude", "AgentRefused", "AgentTruncated", "AgentInvalid", "CassetteTransport", "image_block"):
        assert hasattr(client, name), f"client.{name} must exist"
    for name in ("FakeTransport", "fake_response"):
        assert hasattr(fakes, name), f"fakes.{name} must exist"


def call(transport, ledger, system=None, content=None):
    return asyncio.run(client.Claude(transport, ledger, {"writer.draft": "fake-writer"}).call(
        "writer.draft", Schema,
        system=system if system is not None else [{"type": "text", "text": "A"}],
        content=content if content is not None else [{"type": "text", "text": "Q"}],
    ))


def test_D1_request_response_and_usage():
    interfaces()
    system = [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]
    content = [{"type": "text", "text": "Q"}]
    response = fakes.fake_response('{"title": "One pilot"}', usage={"input_tokens": 7, "output_tokens": 3})
    transport = fakes.FakeTransport({"fake-writer": [response]})
    ledger = Ledger()
    assert call(transport, ledger, system, content) == Schema(title="One pilot")
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert list(request) == ["model", "max_tokens", "system", "messages", "output_config"]
    assert request["model"] == "fake-writer" and request["max_tokens"] == 16000
    assert request["messages"] == [{"role": "user", "content": content}]
    assert request["system"] == [system[0], {**system[1], "cache_control": {"type": "ephemeral"}}]
    assert system == [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]
    assert request["output_config"]["effort"] == "medium"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert request["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert "thinking" not in request and "temperature" not in request
    assert ledger.entries == [("writer.draft", "fake-writer", {"input_tokens": 7, "output_tokens": 3,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})]


def test_D1_text_blocks():
    interfaces()
    response = fakes.fake_response(None)
    response["content"] = [{"type": "text", "text": '{"title": '}, {"type": "text", "text": '"One pilot"}'}]
    assert call(fakes.FakeTransport({"fake-writer": [response]}), Ledger()) == Schema(title="One pilot")


@pytest.mark.parametrize(("reason", "exception"), [("refusal", "AgentRefused"), ("max_tokens", "AgentTruncated")])
def test_D2_stop_reasons(reason, exception):
    interfaces()
    transport = fakes.FakeTransport({"fake-writer": [fakes.fake_response(None, stop_reason=reason)]})
    ledger = Ledger()
    with pytest.raises(getattr(client, exception), match="writer.draft"):
        call(transport, ledger)
    assert len(transport.requests) == len(ledger.entries) == 1


def test_D3_retry_and_invalid():
    interfaces()
    invalid = fakes.fake_response('{"title": 42}')
    valid = fakes.fake_response('{"title": "One pilot"}')
    transport = fakes.FakeTransport({"fake-writer": [invalid, valid]})
    ledger = Ledger()
    assert call(transport, ledger) == Schema(title="One pilot")
    assert len(transport.requests) == len(ledger.entries) == 2
    block = transport.requests[1]["messages"][0]["content"][-1]
    assert block["type"] == "text"
    assert block["text"].startswith("Your previous output failed validation:")
    assert "title" in block["text"] and "Return valid output." in block["text"]
    assert "https://errors.pydantic.dev" not in block["text"]
    transport = fakes.FakeTransport({"fake-writer": [invalid, invalid]})
    with pytest.raises(client.AgentInvalid, match="writer.draft"):
        call(transport, Ledger())
    assert len(transport.requests) == 2


def test_D4_determinism_cassette_and_image(tmp_path):
    interfaces()
    fake = fakes.FakeTransport({"fake-writer": [fakes.fake_response('{"title": "One pilot"}')]})
    path = tmp_path / "cassette.json"
    assert call(client.CassetteTransport(Cassette(path, "record", transport=fake)), Ledger()) == Schema(title="One pilot")
    assert call(client.CassetteTransport(Cassette(path)), Ledger()) == Schema(title="One pilot")
    assert len(fake.requests) == 1
    second = fakes.FakeTransport({"fake-writer": [fakes.fake_response('{"title": "One pilot"}')]})
    assert call(second, Ledger()) == Schema(title="One pilot")
    assert json.dumps(fake.requests[0]) == json.dumps(second.requests[0])
    png = tmp_path / "sample.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nexample")
    block = client.image_block(png)
    assert block == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgpleGFtcGxl"}}
    assert base64.b64decode(block["source"]["data"]) == png.read_bytes()


def test_D5_dependency_lazy_import_and_sdk_boundary():
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert any(dep.split(">=")[0].split("[")[0].strip() == "anthropic" for dep in project["project"]["dependencies"])
    assert client is not None and isinstance(getattr(client, "AnthropicTransport", None), type)
    result = subprocess.run([sys.executable, "-c", "import sys; import docla.agents.client; print('anthropic' in sys.modules)"],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"
    imports = []
    for path in (root / "src/docla").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import) and any(a.name == "anthropic" or a.name.startswith("anthropic.") for a in node.names):
                imports.append(path.relative_to(root).as_posix())
            if isinstance(node, ast.ImportFrom) and node.module and (node.module == "anthropic" or node.module.startswith("anthropic.")):
                imports.append(path.relative_to(root).as_posix())
    assert set(imports) == {"src/docla/agents/client.py"}
