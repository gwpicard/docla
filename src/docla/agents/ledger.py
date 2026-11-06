"""Record the cost of each agent call."""

import json
from pathlib import Path

from docla.config import Price


class BudgetExceeded(Exception):
    """The document budget has been reached."""


class PriceMissing(Exception):
    """No price is configured for a model."""


class Ledger:
    def __init__(self, path: Path, prices: dict[str, Price], max_usd: float | None = None) -> None:
        self.path = path
        self.prices = prices
        self.max_usd = max_usd
        self.total = 0.0

    def add(self, role: str, model: str, usage: dict[str, int]) -> float:
        if model not in self.prices:
            raise PriceMissing(f"No price for model {model}")
        price = self.prices[model]
        input_tokens = usage.get("input_tokens", 0)
        output = usage.get("output_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_write = usage.get("cache_creation_input_tokens", 0)
        usd = (
            input_tokens * price.input
            + output * price.output
            + cache_read * price.cache_read
            + cache_write * price.cache_write
        ) / 1_000_000
        record = {
            "role": role,
            "model": model,
            "input": input_tokens,
            "cache_read": cache_read,
            "cache_write": cache_write,
            "output": output,
            "usd": usd,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(record) + "\n")
        self.total += usd
        if self.max_usd is not None and self.total >= self.max_usd:
            raise BudgetExceeded(f"Budget reached: ${self.total}")
        return usd
