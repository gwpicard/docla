"""Bounded execution and retry of transport calls."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
RETRY_STATUSES = frozenset({429, *range(500, 600)})


class TransportError(Exception):
    def __init__(self, status: int, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class Scheduler:
    def __init__(
        self,
        max_concurrency: int = 4,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
        max_tries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._sleep = sleep
        self._rng = rng if rng is not None else random.Random()
        self._max_tries = max_tries
        self._base_delay = base_delay
        self._max_delay = max_delay

    async def run(self, job: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._semaphore:
                    return await job()
            except TransportError as error:
                if error.status not in RETRY_STATUSES or attempt >= self._max_tries:
                    raise
                delay = error.retry_after
                if delay is None:
                    delay = min(self._max_delay, self._base_delay * 2 ** (attempt - 1))
                    delay *= self._rng.uniform(0.5, 1.0)
                await self._sleep(delay)
