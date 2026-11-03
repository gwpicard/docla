"""Record and replay Claude responses so tests are fast, free and deterministic."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

Transport = Callable[[dict[str, Any]], dict[str, Any]]

SECRET_FIELDS = ("api_key", "authorization", "headers")
REDACTED = "[redacted]"


class CassetteMiss(KeyError):
    """Raised in replay mode when a request has no recording."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


def _key(request: dict[str, Any]) -> str:
    kept = {k: v for k, v in request.items() if k not in SECRET_FIELDS}
    canonical = json.dumps(kept, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _redact(request: dict[str, Any]) -> dict[str, Any]:
    return {k: (REDACTED if k in SECRET_FIELDS else v) for k, v in request.items()}


class Cassette:
    def __init__(
        self,
        path: Path,
        mode: Literal["replay", "record"] = "replay",
        transport: Transport | None = None,
    ) -> None:
        self.path = Path(path)
        self.mode = mode
        self.transport = transport

    @classmethod
    def from_env(cls, path: Path, transport: Transport | None = None) -> Cassette:
        if os.environ.get("DOCLA_RECORD") == "1":
            return cls(path, "record", transport)
        return cls(path, "replay", transport)

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        key = _key(request)
        if self.mode == "record":
            return self._record(key, request)
        entries = self._load()
        if key not in entries:
            raise CassetteMiss(f"No recording for request {key} in {self.path}. Run with DOCLA_RECORD=1 to record it.")
        response: dict[str, Any] = entries[key]["response"]
        return response

    def _record(self, key: str, request: dict[str, Any]) -> dict[str, Any]:
        if self.transport is None:
            raise ValueError("record mode needs a transport")
        response = self.transport(request)
        entries = self._load()
        entries[key] = {"request": _redact(request), "response": response}
        text = json.dumps(entries, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        return response

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        entries: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        return entries
