# Intent: Schedule bounded Claude calls with deterministic retries and transport errors.

import asyncio
import importlib
import random
import subprocess
import sys
from types import SimpleNamespace

import pytest

try:
    scheduler = importlib.import_module("docla.agents.scheduler")
except ImportError as error:
    if error.name != "docla.agents.scheduler" and not str(error.name).startswith("docla.agents.scheduler."):
        raise
    scheduler = None

try:
    client = importlib.import_module("docla.agents.client")
except ImportError as error:
    if error.name != "docla.agents.client" and not str(error.name).startswith("docla.agents.client."):
        raise
    client = None


def require_scheduler():
    assert scheduler is not None, "docla.agents.scheduler must exist"
    assert hasattr(scheduler, "Scheduler"), "Scheduler must exist"
    assert hasattr(scheduler, "TransportError"), "TransportError must exist"
    return scheduler


@pytest.mark.parametrize("cap", [None, 3])
def test_D1_concurrency_and_order(cap):
    module = require_scheduler()

    async def exercise():
        active = 0
        peak = 0
        reached = asyncio.Event()
        release = asyncio.Event()
        expected_cap = 4 if cap is None else 3

        async def sleep(delay):
            raise AssertionError(f"unexpected retry sleep: {delay}")

        runner = module.Scheduler() if cap is None else module.Scheduler(max_concurrency=cap, sleep=sleep)

        async def job(index):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active >= expected_cap:
                reached.set()
            await release.wait()
            active -= 1
            return index

        tasks = [asyncio.create_task(runner.run(lambda i=i: job(i))) for i in range(8)]
        try:
            await asyncio.wait_for(reached.wait(), 1)
            await asyncio.sleep(0)
            assert peak == expected_cap
        finally:
            release.set()
            results = await asyncio.gather(*tasks)
        assert results == list(range(8))
        assert peak == expected_cap

    asyncio.run(exercise())


@pytest.mark.parametrize("status", [503, 429])
def test_D2_transient_error_then_success(status):
    module = require_scheduler()
    calls = 0
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    async def job():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise module.TransportError(status)
        return "ok"

    assert asyncio.run(module.Scheduler(sleep=sleep).run(job)) == "ok"
    assert calls == 3
    assert len(sleeps) == 2


@pytest.mark.parametrize("status,tries", [(400, 5), (500, 5), (500, 2)])
def test_D2_terminal_error_is_unchanged(status, tries):
    module = require_scheduler()
    errors = []
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    async def job():
        error = module.TransportError(status, str(len(errors)))
        errors.append(error)
        raise error

    runner = module.Scheduler(sleep=sleep) if tries == 5 else module.Scheduler(sleep=sleep, max_tries=tries)
    with pytest.raises(module.TransportError) as caught:
        asyncio.run(runner.run(job))
    expected_calls = 1 if status == 400 else tries
    assert len(errors) == expected_calls
    assert len(sleeps) == expected_calls - 1
    assert caught.value is errors[-1]


def test_D3_retry_after_is_exact():
    module = require_scheduler()
    sleeps = []
    calls = 0

    async def sleep(delay):
        sleeps.append(delay)

    async def job():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise module.TransportError(429, retry_after=7.5)
        return "ok"

    assert asyncio.run(module.Scheduler(sleep=sleep).run(job)) == "ok"
    assert sleeps == [7.5]
    assert calls == 2


def test_D4_seeded_backoff_and_cap():
    module = require_scheduler()

    def run_once():
        sleeps = []

        async def sleep(delay):
            sleeps.append(delay)

        async def job():
            raise module.TransportError(500)

        runner = module.Scheduler(sleep=sleep, rng=random.Random(7), base_delay=1.0, max_delay=4.0)
        with pytest.raises(module.TransportError):
            asyncio.run(runner.run(job))
        return sleeps

    sleeps = run_once()
    assert sleeps == run_once()
    assert len(sleeps) == 4
    for delay, ceiling in zip(sleeps, [1.0, 2.0, 4.0, 4.0], strict=True):
        assert 0.5 * ceiling <= delay <= ceiling


def test_D5_status_error_translation():
    module = require_scheduler()
    assert client is not None and hasattr(client, "AnthropicTransport"), "AnthropicTransport must exist"
    import anthropic
    import httpx2 as httpx  # anthropic 2.6.0 depends on httpx2, not httpx

    response = httpx.Response(429, headers={"retry-after": "3"}, request=httpx.Request("POST", "https://example.com"))
    sdk_error = anthropic.RateLimitError("limited", response=response, body=None)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise sdk_error

    transport = client.AnthropicTransport(client=SimpleNamespace(messages=SimpleNamespace(create=create)))
    with pytest.raises(module.TransportError) as caught:
        transport({"model": "test", "messages": []})
    assert len(calls) == 1
    assert caught.value.status == 429
    assert caught.value.retry_after == 3.0
    assert caught.value.__cause__ is sdk_error


def test_D5_default_client_disables_sdk_retries(monkeypatch):
    assert client is not None and hasattr(client, "AnthropicTransport"), "AnthropicTransport must exist"
    import anthropic

    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    original = anthropic.Anthropic
    constructed = []

    def make_client(*args, **kwargs):
        result = original(*args, **kwargs)
        constructed.append(result)
        return result

    monkeypatch.setattr(anthropic, "Anthropic", make_client)
    client.AnthropicTransport()
    assert len(constructed) == 1
    assert constructed[0].max_retries == 0


def test_D5_scheduler_import_does_not_load_anthropic():
    require_scheduler()
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import docla.agents.scheduler; print('anthropic' in sys.modules)"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
