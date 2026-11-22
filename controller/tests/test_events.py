"""events.py: the envelope, seq, hello, slow connections and level throttling (events.md)."""

import asyncio
import json
import re

import pytest

from contract import assert_schema
from spotivault.api.models import Connection
from spotivault.events import (
    HELLO_KEYS,
    QUEUE_LIMIT,
    EventBus,
    SubscriptionOverflow,
    merge_levels,
)
from spotivault.fake.clock import FakeClock
from spotivault.services import Services

LEVEL = {
    "peak_dbfs": -3.0,
    "rms_dbfs": -17.0,
    "channels": [{"peak_dbfs": -3.0, "rms_dbfs": -17.0}, {"peak_dbfs": -4.0, "rms_dbfs": -18.0}],
}


def make_bus() -> EventBus:
    bus = EventBus(FakeClock(), version="0.1.0", boot_id="boot")
    for key in HELLO_KEYS:
        bus.add_snapshot(key, _none)
    return bus


async def _none() -> None:
    return None


def test_envelope_and_seq() -> None:
    bus = make_bus()
    first = bus.publish("connection", {"state": "ok"})
    second = bus.publish("setup.state", {"completed": False})
    assert (first.seq, second.seq, bus.seq) == (1, 2, 2)
    envelope = json.loads(second.to_json())
    assert list(envelope) == ["seq", "type", "at", "data"]
    assert envelope["type"] == "setup.state"
    assert envelope["data"] == {"completed": False}
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", envelope["at"])


def test_models_are_converted_and_copied() -> None:
    bus = make_bus()
    data = {"items": [1]}
    event = bus.publish("run.queue", data)
    data["items"].append(2)
    assert event.data == {"items": [1]}
    model = Connection(
        state="ok",
        display_name="Lorne",
        user_id="lorne",
        client_id_masked="0123…cdef",
        authorized_at="2026-11-12T20:00:00Z",
        expires_at="2027-05-12T20:00:00Z",
        scopes=[],
    )
    event = bus.publish("connection", model)
    assert_schema("Connection", event.data)


def test_unknown_types_are_refused() -> None:
    bus = make_bus()
    for bad in ("hello", "level", "run.stat", "log.line"):
        with pytest.raises(ValueError):
            bus.publish(bad, {})
    with pytest.raises(TypeError):
        bus.publish("connection", [1, 2])


async def test_hello_then_every_later_event_in_order() -> None:
    bus = make_bus()
    bus.publish("connection", {"n": 1})
    async with bus.subscribe() as sub:
        assert sub.hello is not None
        assert sub.hello.type == "hello"
        assert sub.hello.seq == 1
        assert set(sub.hello.data) == {"boot_id", "version", *HELLO_KEYS}
        assert sub.hello.data["boot_id"] == "boot"
        bus.publish("connection", {"n": 2})
        bus.publish("connection", {"n": 3})
        got = [await sub.next(), await sub.next()]
        assert [e.seq for e in got] == [2, 3]
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0


async def test_hello_snapshot_comes_from_the_providers(services: Services) -> None:
    async with services.bus.subscribe() as sub:
        assert sub.hello is not None
        data = sub.hello.data
    assert_schema("Setup", data["setup"])
    assert_schema("Status", data["status"])
    assert_schema("Connection", data["connection"])
    assert_schema("ClientStatus", data["client"])
    assert data["backlog"] is None


async def test_a_provider_can_be_replaced() -> None:
    bus = make_bus()

    async def ok() -> dict:
        return {"state": "ok"}

    bus.add_snapshot("connection", ok)
    assert (await bus.snapshot())["connection"] == {"state": "ok"}
    with pytest.raises(ValueError):
        bus.add_snapshot("nonsense", ok)


async def test_events_published_while_hello_is_built_follow_it() -> None:
    bus = make_bus()
    gate = asyncio.Event()

    async def slow_setup() -> dict:
        bus.publish("setup.state", {"during": True})
        await gate.wait()
        return {"x": 1}

    bus.add_snapshot("setup", slow_setup)
    entered = asyncio.Event()

    async def subscriber() -> list[int | None]:
        async with bus.subscribe() as sub:
            entered.set()
            assert sub.hello is not None
            return [sub.hello.seq, (await sub.next()).seq]

    task = asyncio.create_task(subscriber())
    await asyncio.sleep(0)
    gate.set()
    hello_seq, next_seq = await task
    assert (hello_seq, next_seq) == (0, 1)


async def test_a_slow_connection_is_dropped_at_the_limit() -> None:
    bus = make_bus()
    async with bus.subscribe() as sub:
        for i in range(QUEUE_LIMIT):
            bus.publish("connection", {"i": i})
        assert bus.subscriber_count == 1
        bus.publish("connection", {"i": "one too many"})
        assert bus.subscriber_count == 0
        with pytest.raises(SubscriptionOverflow):
            await sub.next()


async def test_level_is_volatile_and_latest_wins() -> None:
    bus = make_bus()
    async with bus.subscribe() as sub:
        bus.publish_level(LEVEL)
        event = await sub.next()
        assert event.type == "level"
        assert event.seq is None
        assert json.loads(event.to_json())["seq"] is None
        # Many levels while the client is behind: only the latest is kept, and none count
        # towards the queue limit.
        for _ in range(QUEUE_LIMIT + 10):
            bus._send_level(dict(LEVEL, rms_dbfs=-20.0), 0.0)
        assert bus.subscriber_count == 1
        latest = await sub.next()
        assert latest.data["rms_dbfs"] == -20.0
        bus.publish("connection", {"n": 1})
        assert (await sub.next()).type == "connection"


async def test_level_is_throttled_and_merged() -> None:
    bus = make_bus()
    async with bus.subscribe() as sub:
        bus.publish_level(LEVEL)  # sent at once
        bus.publish_level(dict(LEVEL, peak_dbfs=-1.0, rms_dbfs=-15.0))  # within 100 ms: held
        bus.publish_level(dict(LEVEL, peak_dbfs=-6.0, rms_dbfs=-16.0))  # merged into it
        first = await sub.next()
        assert first.data["peak_dbfs"] == -3.0
        merged = await asyncio.wait_for(sub.next(), 1.0)  # after the 100 ms window
        assert merged.data["peak_dbfs"] == -1.0  # the highest peak
        assert merged.data["rms_dbfs"] == -16.0  # the latest RMS


def test_merge_levels_per_channel() -> None:
    older = {
        "peak_dbfs": -2.0,
        "rms_dbfs": -10.0,
        "channels": [{"peak_dbfs": -2.0, "rms_dbfs": -10.0}],
    }
    newer = {
        "peak_dbfs": -5.0,
        "rms_dbfs": -12.0,
        "channels": [{"peak_dbfs": -5.0, "rms_dbfs": -12.0}],
    }
    merged = merge_levels(older, newer)
    assert merged == {
        "peak_dbfs": -2.0,
        "rms_dbfs": -12.0,
        "channels": [{"peak_dbfs": -2.0, "rms_dbfs": -12.0}],
    }
