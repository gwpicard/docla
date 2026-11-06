"""Fake Claude responses and transport."""

from typing import Any

from docla.agents.client import USAGE_KEYS


def fake_response(
    text: str | None,
    stop_reason: str = "end_turn",
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    values = usage or {}
    return {
        "type": "message",
        "role": "assistant",
        "model": "fake",
        "content": [] if text is None else [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "usage": {key: values.get(key, 0) for key in USAGE_KEYS},
    }


class FakeTransport:
    def __init__(self, responses: dict[str, list[dict[str, Any]]]) -> None:
        self.responses = {model: list(items) for model, items in responses.items()}
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        model = request["model"]
        if not self.responses.get(model):
            raise AssertionError(f"No response for model {model}")
        return self.responses[model].pop(0)
