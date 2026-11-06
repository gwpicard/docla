"""Structured Claude calls through an injectable transport."""

import asyncio
import base64
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from docla.agents.cassette import Cassette, Transport

T = TypeVar("T", bound=BaseModel)
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


class AgentRefused(Exception):
    """The agent refused the request."""


class AgentTruncated(Exception):
    """The agent ran out of output tokens."""


class AgentInvalid(Exception):
    """The agent failed to produce valid output."""


class UsageLedger(Protocol):
    def add(self, role: str, model: str, usage: dict[str, int]) -> object: ...


def image_block(png: Path) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(png.read_bytes()).decode("ascii"),
        },
    }


def _strict_schema(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            value["additionalProperties"] = False
        for child in value.values():
            _strict_schema(child)
    elif isinstance(value, list):
        for child in value:
            _strict_schema(child)


def _validation_message(error: ValidationError) -> str:
    details = "; ".join(f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in error.errors(include_url=False))
    return f"Your previous output failed validation: {details}. Return valid output."


class Claude:
    def __init__(self, transport: Transport, ledger: UsageLedger, models: dict[str, str]) -> None:
        self.transport = transport
        self.ledger = ledger
        self.models = models

    async def call(
        self,
        role: str,
        schema: type[T],
        *,
        system: list[dict[str, Any]],
        content: list[dict[str, Any]],
        effort: Literal["low", "medium", "high"] = "medium",
        max_tokens: int = 16000,
    ) -> T:
        if role not in self.models:
            raise ValueError(f"No model for role {role}")
        model = self.models[role]
        blocks = deepcopy(system)
        if blocks and not any("cache_control" in block for block in blocks):
            blocks[-1]["cache_control"] = {"type": "ephemeral"}
        output_schema = schema.model_json_schema()
        _strict_schema(output_schema)
        request = {
            "model": model,
            "max_tokens": max_tokens,
            "system": blocks,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": output_schema}},
        }
        for attempt in range(2):
            response = await asyncio.to_thread(self.transport, request)
            usage = response.get("usage") or {}
            self.ledger.add(role, model, {key: usage.get(key) or 0 for key in USAGE_KEYS})
            if response.get("stop_reason") == "refusal":
                raise AgentRefused(f"Agent {role} refused")
            if response.get("stop_reason") == "max_tokens":
                raise AgentTruncated(f"Agent {role} was truncated")
            text = "".join(block["text"] for block in response.get("content", []) if block.get("type") == "text")
            try:
                return schema.model_validate_json(text)
            except ValidationError as error:
                if attempt:
                    raise AgentInvalid(f"Agent {role} returned invalid output") from error
                request = {
                    **request,
                    "messages": [
                        {"role": "user", "content": [*content, {"type": "text", "text": _validation_message(error)}]}
                    ],
                }
        raise AgentInvalid(f"Agent {role} returned invalid output")


class CassetteTransport:
    def __init__(self, cassette: Cassette) -> None:
        self.cassette = cassette

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.cassette.call(request)


class AnthropicTransport:
    def __init__(self, client: Any | None = None) -> None:
        import anthropic

        self.client = client if client is not None else anthropic.Anthropic()

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self.client.messages.create(**request).model_dump(mode="json")
        return result
