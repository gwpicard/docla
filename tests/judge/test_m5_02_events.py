# Intent: Relay published events to visualiser clients with keepalives.
import asyncio
import importlib
import importlib.util

import pytest


def _subject(name):
    try:
        return importlib.import_module(name)
    except ImportError as error:
        if not error.name or not (name == error.name or name.startswith(error.name + ".")):
            raise
        try:
            spec = importlib.util.find_spec(error.name)
        except ModuleNotFoundError as missing:
            if not missing.name or not error.name.startswith(missing.name + "."):
                raise
            spec = None
        if spec is not None:
            raise
        return None


events = _subject("docla.server.events")
app_module = _subject("docla.server.app")


def _bus():
    assert events is not None and hasattr(events, "EventBus"), "EventBus must exist"
    return events.EventBus()


def _app(folder):
    assert app_module is not None and hasattr(app_module, "create_app"), "create_app must exist"
    return app_module.create_app(folder, "t0ken")


def test_D1_fanout_unsubscribe_and_history():
    bus = _bus()
    first, second = bus.subscribe(), bus.subscribe()
    data = {"doc": "deck", "rev": 3, "by": "human"}
    bus.publish("doc.changed", data)
    expected = {"type": "doc.changed", "data": data}
    assert first.get_nowait() == expected
    assert second.get_nowait() == expected
    bus.unsubscribe(first)
    bus.publish("job.started", {"job": "j1"})
    assert first.empty()
    assert second.get_nowait() == {"type": "job.started", "data": {"job": "j1"}}
    assert bus.recent() == [expected, {"type": "job.started", "data": {"job": "j1"}}]
    assert bus.subscriber_count() == 1


def test_D2_event_types_and_reject_unknown():
    bus = _bus()
    assert hasattr(events, "EVENT_TYPES")
    assert isinstance(events.EVENT_TYPES, tuple)
    assert set(events.EVENT_TYPES) == {
        "doc.changed", "job.started", "job.progress", "job.finished", "section.state",
        "section.attempt", "look.progress", "build.finished", "learning.proposed", "queue.changed",
    }
    queue = bus.subscribe()
    with pytest.raises(ValueError):
        bus.publish("doc.renamed", {})
    assert queue.empty()
    assert bus.recent() == []


def _scope(headers):
    return {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http", "path": "/api/events",
        "raw_path": b"/api/events", "query_string": b"", "root_path": "",
        "headers": headers, "server": ("127.0.0.1", 8765), "client": ("127.0.0.1", 1234),
    }


async def _stream(app, headers, action):
    messages = []
    disconnected = asyncio.Event()
    changed = asyncio.Event()
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        changed.set()

    task = asyncio.create_task(app(_scope(headers), receive, send))

    async def wait_for(predicate):
        async def wait():
            while not predicate():
                changed.clear()
                if predicate():
                    return
                await changed.wait()
        await asyncio.wait_for(wait(), 1)

    try:
        await action(messages, wait_for)
    finally:
        disconnected.set()
        await asyncio.wait_for(task, 1)
    return messages


def _body(messages):
    return b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")


def test_D3_app_state_and_streamed_event(tmp_path):
    app = _app(tmp_path)
    assert events is not None and hasattr(events, "EventBus")
    assert isinstance(app.state.bus, events.EventBus)
    assert app.state.keepalive == 15.0

    async def check():
        async def action(messages, wait_for):
            await wait_for(lambda: any(m["type"] == "http.response.start" for m in messages))
            start = next(m for m in messages if m["type"] == "http.response.start")
            assert start["status"] == 200
            headers = dict(start["headers"])
            assert headers[b"content-type"].split(b";")[0] == b"text/event-stream"
            assert headers[b"cache-control"] == b"no-cache"
            async def subscribed():
                while app.state.bus.subscriber_count() != 1:
                    await asyncio.sleep(0.001)
            await asyncio.wait_for(subscribed(), 1)
            app.state.bus.publish("doc.changed", {"doc": "deck", "rev": 3, "by": "human"})
            expected = b'event: doc.changed\ndata: {"doc": "deck", "rev": 3, "by": "human"}\n\n'
            await wait_for(lambda: expected in _body(messages))
            assert expected in _body(messages)
        await _stream(app, [(b"host", b"127.0.0.1:8765"), (b"x-docla-token", b"t0ken")], action)
    asyncio.run(check())


def test_D4_keepalive_and_disconnect_unsubscribes(tmp_path):
    app = _app(tmp_path)
    assert hasattr(app.state, "bus") and hasattr(app.state, "keepalive")
    app.state.keepalive = 0.05

    async def check():
        async def action(messages, wait_for):
            await wait_for(lambda: b": keepalive\n\n" in _body(messages))
            assert b": keepalive\n\n" in _body(messages)
            assert app.state.bus.subscriber_count() == 1
        await _stream(app, [(b"host", b"127.0.0.1:8765"), (b"x-docla-token", b"t0ken")], action)
        assert app.state.bus.subscriber_count() == 0
    asyncio.run(check())


def test_D5_security_remains_in_force(tmp_path):
    app = _app(tmp_path)

    async def check():
        async def status(headers):
            async def action(messages, wait_for):
                await wait_for(lambda: any(m["type"] == "http.response.start" for m in messages))
            messages = await _stream(app, headers, action)
            return next(m["status"] for m in messages if m["type"] == "http.response.start")
        assert await status([(b"host", b"127.0.0.1:8765")]) == 401
        assert await status([(b"host", b"evil.example"), (b"x-docla-token", b"t0ken")]) == 403
    asyncio.run(check())
