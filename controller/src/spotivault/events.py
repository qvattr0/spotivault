"""The live event bus behind `WS /api/events` (contracts/events.md).

Modules publish; every WS connection has its own `Subscription`:

    services.bus.publish("client.status", status)        # a pydantic model or a dict
    services.bus.publish_level({"peak_dbfs": -3.1, ...})  # the level meter, throttled

    async with services.bus.subscribe() as sub:           # in the WS handler
        await ws.send_text(sub.hello.to_json())
        while True:
            event = await sub.next()                      # raises SubscriptionOverflow

Rules from events.md that this module enforces:
- **Envelope:** `{seq, type, at, data}`. `seq` counts from 1 per controller process, with no gaps;
  `at` is RFC 3339 UTC with milliseconds.
- **Publish after commit:** call `publish` only once the state it describes is in the database,
  so a REST read made after the event already shows it. Call it from the event loop's thread.
- **hello:** the first event on each connection, built from the snapshot providers modules
  register with `add_snapshot`. Its `seq` is the last event published before the connection
  subscribed; every later event reaches the connection, in order.
- **Slow clients:** 256 unsent events per connection, then `next()` raises SubscriptionOverflow
  and the handler closes the socket with 1013.
- **level:** volatile (`seq` null), at most one per 100 ms with merging, latest wins per
  connection, never counted in the 256. Whoever relays Spytify's `level` sends it only while the
  session is `recording` or `stopping`.
- **log.lines:** volatile too, and only to the connections that follow the logs
  (`Subscription.log_follow`, set by the logs module, logview/service.py). An unsent batch is
  merged with the next one, keeping the newest LOG_BATCH_MAX lines and counting the rest in
  `dropped`. Never counted in the 256.
"""

import asyncio
import json
import logging
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic_core import to_jsonable_python

from spotivault.clock import iso_ms
from spotivault.ports import Clock

log = logging.getLogger(__name__)

# Every event type in events.md. `hello` and `level` have their own methods.
EVENT_TYPES = frozenset(
    {
        "run.state",
        "run.queue",
        "item.state",
        "run.finished",
        "backlog",
        "track.started",
        "track.finished",
        "track.skipped",
        "session.state",
        "device.moved",
        "error",
        "library.item",
        "album.item",
        "catalog.refresh",
        "setup.state",
        "client.install",
        "client.status",
        "connection",
    }
)

# The hello snapshot's keys besides boot_id and version, each filled by a provider.
HELLO_KEYS = ("setup", "status", "connection", "client", "backlog")

QUEUE_LIMIT = 256  # unsent events per connection before it's closed with 1013
LEVEL_INTERVAL_S = 0.1  # at most 10 `level` events a second
LOG_BATCH_MAX = 200  # lines in one `log.lines` event, at most (events.md § Logs)

type Payload = Any  # a pydantic model, or a dict of JSON-able values (models inside are fine)
type SnapshotProvider = Callable[[], Awaitable[Payload]]


@dataclass(frozen=True, slots=True)
class Event:
    """One event, as sent: `{"seq": 1834, "type": "item.state", "at": "…Z", "data": {…}}`."""

    seq: int | None
    type: str
    at: datetime
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "type": self.type, "at": iso_ms(self.at), "data": self.data}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


class SubscriptionOverflow(Exception):
    """The connection fell QUEUE_LIMIT events behind. Close it with 1013; the client reconnects."""


class Subscription:
    """One connection's view of the bus: its hello, then every event published after it."""

    def __init__(self, hello_seq: int) -> None:
        self.hello_seq = hello_seq
        self.hello: Event | None = None
        self.overflowed = False
        self._queue: deque[Event] = deque()
        self._level: Event | None = None
        self._logs: Event | None = None
        self._wakeup = asyncio.Event()
        # What this connection follows of the logs (the logs module's object), or None.
        self.log_follow: Any = None

    async def next(self) -> Event:
        """The next event to send: queued events first, then the latest `level`, then the
        pending `log.lines`, if any."""
        while True:
            if self.overflowed:
                raise SubscriptionOverflow
            if self._queue:
                return self._queue.popleft()
            if self._level is not None:
                level, self._level = self._level, None
                return level
            if self._logs is not None:
                logs, self._logs = self._logs, None
                return logs
            self._wakeup.clear()
            await self._wakeup.wait()

    def push_logs(
        self, lines: list[dict[str, Any]], *, at: datetime, follow_id: Any, dropped: int = 0
    ) -> None:
        """Sends a `log.lines` batch (events.md § Logs). If the last one hasn't gone out yet and
        is for the same follow, the two are merged: the newest LOG_BATCH_MAX lines are kept, and
        the rest counted in `dropped`. One for an older follow is replaced."""
        pending = self._logs
        if pending is not None and pending.data["follow_id"] == follow_id:
            lines = pending.data["lines"] + lines
            dropped += pending.data["dropped"]
        if len(lines) > LOG_BATCH_MAX:
            dropped += len(lines) - LOG_BATCH_MAX
            lines = lines[-LOG_BATCH_MAX:]
        data = {"lines": lines, "dropped": dropped, "follow_id": follow_id}
        self._logs = Event(seq=None, type="log.lines", at=at, data=data)
        self._wakeup.set()

    def _push(self, event: Event) -> bool:
        """Queues an event. False when the queue is full: the subscription is then dead."""
        if len(self._queue) >= QUEUE_LIMIT:
            self.overflowed = True
            self._queue.clear()
            self._wakeup.set()
            return False
        self._queue.append(event)
        self._wakeup.set()
        return True

    def _push_level(self, event: Event) -> None:
        self._level = event  # latest wins: an unsent older level is replaced
        self._wakeup.set()


class EventBus:
    """Publishes events to every subscription and builds the `hello` snapshot."""

    def __init__(self, clock: Clock, *, version: str, boot_id: str | None = None) -> None:
        self.clock = clock
        self.version = version
        self.boot_id = boot_id or str(uuid.uuid4())  # hello.boot_id and Health.boot_id
        self._seq = 0
        self._subscriptions: set[Subscription] = set()
        self._snapshots: dict[str, SnapshotProvider] = {}
        self._level_pending: dict[str, Any] | None = None
        self._level_last_sent: float | None = None
        self._level_timer: asyncio.TimerHandle | None = None

    @property
    def seq(self) -> int:
        """The seq of the last event published."""
        return self._seq

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    def log_followers(self) -> list[Subscription]:
        """The connections that follow the logs (events.md § Logs)."""
        return [sub for sub in self._subscriptions if sub.log_follow is not None]

    def publish(self, type: str, data: Payload) -> Event:
        """Sends an event to every connection. `type` must be one of EVENT_TYPES.

        `data` is a pydantic model or a dict; it's converted to JSON values now, so later changes
        to the object don't leak into the event.
        """
        if type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {type!r} (see contracts/events.md)")
        self._seq += 1
        event = Event(seq=self._seq, type=type, at=self.clock.now(), data=_to_data(data))
        for sub in list(self._subscriptions):
            if not sub._push(event):
                self._subscriptions.discard(sub)
                log.warning("events: a connection fell %d events behind; closing it", QUEUE_LIMIT)
        return event

    def publish_level(self, data: Payload) -> None:
        """The level meter. At most one per LEVEL_INTERVAL_S: levels in between are merged, the
        highest peaks (overall and per channel) and the latest RMS kept. Must run on the loop."""
        level = _to_data(data)
        if self._level_pending is not None:
            level = merge_levels(self._level_pending, level)
        loop = asyncio.get_running_loop()
        if self._level_timer is not None:
            self._level_pending = level  # sent when the timer fires
            return
        now = loop.time()
        since = None if self._level_last_sent is None else now - self._level_last_sent
        if since is None or since >= LEVEL_INTERVAL_S:
            self._send_level(level, now)
            return
        self._level_pending = level
        self._level_timer = loop.call_later(LEVEL_INTERVAL_S - since, self._flush_level)

    def add_snapshot(self, key: str, provider: SnapshotProvider) -> None:
        """Registers the async function that fills `hello.<key>`. A later call replaces it.

        `key` is one of HELLO_KEYS. The provider returns what the matching REST endpoint returns
        (`setup` is GET /api/setup, `backlog` may be None). It must not raise.
        """
        if key not in HELLO_KEYS:
            raise ValueError(f"hello has no key {key!r}; it has {', '.join(HELLO_KEYS)}")
        self._snapshots[key] = provider

    async def snapshot(self) -> dict[str, Any]:
        """The hello payload: boot_id, version and every HELLO_KEYS value."""
        data: dict[str, Any] = {"boot_id": self.boot_id, "version": self.version}
        for key in HELLO_KEYS:
            provider = self._snapshots.get(key)
            if provider is None:
                raise RuntimeError(f"nothing provides hello.{key}")
            data[key] = to_jsonable_python(await provider(), by_alias=True)
        return data

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[Subscription]:
        """A subscription for one connection, with its `hello` ready.

        It's registered before the snapshot is built, so no event can fall between the two:
        events published while the snapshot is being read are queued after the hello (and may
        repeat a change the snapshot already shows, which is harmless: events carry whole objects).
        """
        sub = Subscription(hello_seq=self._seq)
        self._subscriptions.add(sub)
        try:
            data = await self.snapshot()
            sub.hello = Event(seq=sub.hello_seq, type="hello", at=self.clock.now(), data=data)
            yield sub
        finally:
            self._subscriptions.discard(sub)

    def _send_level(self, level: dict[str, Any], now: float) -> None:
        self._level_pending = None
        self._level_last_sent = now
        event = Event(seq=None, type="level", at=self.clock.now(), data=level)
        for sub in self._subscriptions:
            sub._push_level(event)

    def _flush_level(self) -> None:
        self._level_timer = None
        if self._level_pending is not None:
            self._send_level(self._level_pending, asyncio.get_running_loop().time())


def merge_levels(older: dict[str, Any], newer: dict[str, Any]) -> dict[str, Any]:
    """Two `level` payloads as one: the highest peaks (overall and per channel), the newer RMS."""
    channels = []
    old_channels = older.get("channels") or []
    for i, channel in enumerate(newer.get("channels") or []):
        merged = dict(channel)
        if i < len(old_channels):
            merged["peak_dbfs"] = max(channel["peak_dbfs"], old_channels[i]["peak_dbfs"])
        channels.append(merged)
    return {
        **newer,
        "peak_dbfs": max(newer["peak_dbfs"], older["peak_dbfs"]),
        "channels": channels,
    }


def _to_data(payload: Payload) -> dict[str, Any]:
    data = to_jsonable_python(payload, by_alias=True)
    if not isinstance(data, dict):
        raise TypeError(f"event data must be an object, not {type(data).__name__}")
    return data
