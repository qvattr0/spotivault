"""WS /api/events and WS /vnc in-process, through tests/asgi_ws.py (owner: the web agent).

tests/test_ws_server.py runs the same handlers behind a real uvicorn, for what only it does:
the HTTP upgrade, pings, flow control and closing at shutdown.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI

from asgi_ws import WebSocketClosed, WebSocketRejected, websocket_connect
from contract import assert_schema
from spotivault.events import HELLO_KEYS, QUEUE_LIMIT
from spotivault.services import Services
from spotivault.web.sockets import origin_allowed

# --- WS /api/events ------------------------------------------------------------------------------


async def receive_marked(ws: Any, next_seq: int, count: int) -> list[dict[str, Any]]:
    """Reads events until `count` of them carry a "mark" in their data (the ones this test
    published; other modules publish too), checking that seq counts up from `next_seq` with no
    gap. Returns the marked ones."""
    marked: list[dict[str, Any]] = []
    while len(marked) < count:
        event = await ws.receive_json()
        assert event["seq"] == next_seq, "a gap in seq"
        next_seq += 1
        if "mark" in event["data"]:
            marked.append(event)
    return marked


async def test_events_sends_hello_then_events(running_app: FastAPI, services: Services) -> None:
    services.bus.publish("connection", {"mark": 0})
    async with websocket_connect(running_app, "/api/events") as ws:
        assert ws.subprotocol is None
        hello = await ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["seq"] >= 1  # the event published before it is in the snapshot's past
        services.bus.publish("connection", {"mark": 1})
        services.bus.publish("setup.state", {"mark": 2})
        first, second = await receive_marked(ws, hello["seq"] + 1, 2)
        assert first["seq"] < second["seq"]
        assert (first["type"], second["type"]) == ("connection", "setup.state")
        assert second["data"] == {"mark": 2}
        assert second["at"].endswith("Z")
        await ws.send_text("ignored")
        await ws.send_bytes(b"ignored too")
        services.bus.publish("connection", {"mark": 3})
        (third,) = await receive_marked(ws, second["seq"] + 1, 1)
        assert third["data"] == {"mark": 3}
    await asyncio.sleep(0)
    assert services.bus.subscriber_count == 0


async def test_hello_holds_the_whole_snapshot(running_app: FastAPI, services: Services) -> None:
    async with websocket_connect(running_app, "/api/events") as ws:
        hello = await ws.receive_json()
    assert set(hello) == {"seq", "type", "at", "data"}
    data = hello["data"]
    assert set(data) == {"boot_id", "version", *HELLO_KEYS}
    assert data["boot_id"] == services.bus.boot_id
    assert data["version"] == services.bus.version
    assert_schema("Setup", data["setup"])
    assert_schema("Status", data["status"])
    assert_schema("Connection", data["connection"])
    assert_schema("ClientStatus", data["client"])
    if data["backlog"] is not None:
        assert_schema("Backlog", data["backlog"])


async def test_every_connection_gets_every_event(running_app: FastAPI, services: Services) -> None:
    async with (
        websocket_connect(running_app, "/api/events") as one,
        websocket_connect(running_app, "/api/events") as two,
    ):
        hellos = [await one.receive_json(), await two.receive_json()]
        assert services.bus.subscriber_count == 2
        services.bus.publish("connection", {"mark": 1})
        for ws, hello in zip((one, two), hellos, strict=True):
            (event,) = await receive_marked(ws, hello["seq"] + 1, 1)
            assert event["data"] == {"mark": 1}


async def test_events_closes_with_1011_when_the_hello_fails(
    running_app: FastAPI, services: Services
) -> None:
    async def broken() -> None:
        raise RuntimeError("no backlog")

    services.bus.add_snapshot("backlog", broken)
    async with websocket_connect(running_app, "/api/events") as ws:
        with pytest.raises(WebSocketClosed) as closed:
            await ws.receive()
        assert closed.value.code == 1011
    assert services.bus.subscriber_count == 0


async def test_events_closes_a_slow_connection_with_1013(
    running_app: FastAPI, services: Services
) -> None:
    async with websocket_connect(running_app, "/api/events") as ws:
        await ws.receive_json()  # hello
        sub = next(iter(services.bus._subscriptions))
        sub.overflowed = True
        sub._wakeup.set()
        with pytest.raises(WebSocketClosed) as closed:
            while True:
                await ws.receive()
        assert closed.value.code == 1013


class StalledClient:
    """The ASGI side of a client that stops reading after the hello: every later send waits,
    as uvicorn's does while the client's TCP buffer is full."""

    def __init__(self) -> None:
        self.to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.hello_sent = asyncio.Event()
        self.blocked = asyncio.Event()
        self.reading = asyncio.Event()

    def texts(self) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["type"] == "websocket.send"]

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)
        if message["type"] != "websocket.send":
            return
        if len(self.texts()) == 1:
            self.hello_sent.set()
        else:
            self.blocked.set()
            await self.reading.wait()

    def scope(self, path: str) -> dict[str, Any]:
        return {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "scheme": "ws",
            "server": ("spotivault.test", 80),
            "client": ("127.0.0.1", 50000),
            "root_path": "",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"host", b"spotivault.test")],
            "subprotocols": [],
            "state": {},
            "extensions": {},
        }


async def test_a_client_that_stops_reading_is_closed_with_1013(
    running_app: FastAPI, services: Services
) -> None:
    client = StalledClient()
    handler = asyncio.create_task(
        running_app(client.scope("/api/events"), client.to_app.get, client.send)
    )
    await client.to_app.put({"type": "websocket.connect"})
    await asyncio.wait_for(client.hello_sent.wait(), 5)
    services.bus.publish("connection", {"n": 0})  # sent, and stuck in the client's buffer
    await asyncio.wait_for(client.blocked.wait(), 5)

    for n in range(QUEUE_LIMIT + 1):  # 256 wait, the next one is too many
        services.bus.publish("connection", {"n": n + 1})
    assert services.bus.subscriber_count == 0  # dropped at once: no more memory for it

    client.reading.set()  # the client reads again, and learns it must reconnect
    await asyncio.wait_for(handler, 5)
    last = client.sent[-1]
    assert (last["type"], last["code"]) == ("websocket.close", 1013)
    assert len(client.texts()) == 2  # the hello and n=0; nothing after the overflow


async def test_events_refuses_another_sites_page(running_app: FastAPI, services: Services) -> None:
    with pytest.raises(WebSocketRejected) as rejected:
        async with websocket_connect(
            running_app, "/api/events", headers=[("origin", "https://evil.example")]
        ):
            pass
    assert rejected.value.code == 1008
    assert services.bus.subscriber_count == 0
    async with websocket_connect(
        running_app, "/api/events", headers=[("origin", "http://spotivault.test")]
    ) as ws:
        assert (await ws.receive_json())["type"] == "hello"


@pytest.mark.parametrize(
    ("origin", "host", "allowed"),
    [
        (None, "nas.local:8080", True),  # not a browser
        ("http://nas.local:8080", "nas.local:8080", True),
        ("http://NAS.local:8080", "nas.local:8080", True),
        ("https://192.168.1.20:8080", "192.168.1.20:8080", True),
        ("http://nas.local:9999", "nas.local:8080", False),  # another port is another site
        ("http://evil.example", "nas.local:8080", False),
        ("null", "nas.local:8080", False),
        ("file://", "nas.local:8080", False),
        ("http://[::1", "nas.local:8080", False),
        # The Vite dev server (S7) proxying to a local controller: both on loopback.
        ("http://localhost:5173", "localhost:8181", True),
        ("http://localhost:5173", "127.0.0.1:8080", True),
        ("http://[::1]:5173", "localhost:8080", True),
        # A loopback page may not reach a controller on the LAN, nor the other way round.
        ("http://localhost:5173", "nas.local:8080", False),
        ("http://evil.example", "localhost:8080", False),
        ("http://localhost.evil.example", "localhost:8080", False),
    ],
)
def test_origin_rule(origin: str | None, host: str, allowed: bool) -> None:
    assert origin_allowed(origin, host) is allowed


# --- WS /vnc -------------------------------------------------------------------------------------


async def test_vnc_without_a_server_closes_with_1013(running_app: FastAPI) -> None:
    async with websocket_connect(running_app, "/vnc", subprotocols=["binary"]) as ws:
        assert ws.subprotocol == "binary"
        with pytest.raises(WebSocketClosed) as closed:
            await ws.receive()
        assert closed.value.code == 1013


async def test_vnc_refuses_another_sites_page(running_app: FastAPI) -> None:
    with pytest.raises(WebSocketRejected) as rejected:
        async with websocket_connect(
            running_app, "/vnc", headers=[("origin", "http://evil.example")]
        ):
            pass
    assert rejected.value.code == 1008


class FakeVncServer:
    """A local TCP server that greets like x11vnc ("RFB 003.008\\n"), then echoes in upper case.
    It records what it received and whether the bridge hung up."""

    def __init__(self) -> None:
        self.server: asyncio.Server | None = None
        self.received = bytearray()
        self.hung_up = asyncio.Event()
        self.connections: list[asyncio.StreamWriter] = []

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)

    @property
    def port(self) -> int:
        assert self.server is not None
        return self.server.sockets[0].getsockname()[1]

    async def open_vnc(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_connection("127.0.0.1", self.port)

    async def hang_up(self) -> None:
        for writer in self.connections:
            writer.close()

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            with contextlib.suppress(Exception):
                await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections.append(writer)
        writer.write(b"RFB 003.008\n")
        await writer.drain()
        try:
            while data := await reader.read(65536):
                self.received += data
                writer.write(data.upper())
                await writer.drain()
        except ConnectionError:
            pass
        self.hung_up.set()
        writer.close()


@pytest.fixture
async def vnc_server(services: Services) -> AsyncIterator[FakeVncServer]:
    server = FakeVncServer()
    await server.start()
    services.ports.desktop.open_vnc = server.open_vnc  # type: ignore[method-assign]
    yield server
    await server.stop()


SAME_SITE = [("origin", "http://spotivault.test")]


async def test_vnc_bridges_both_ways(running_app: FastAPI, vnc_server: FakeVncServer) -> None:
    async with websocket_connect(
        running_app, "/vnc", subprotocols=["binary"], headers=SAME_SITE
    ) as ws:
        assert ws.subprotocol == "binary"
        assert await ws.receive_bytes() == b"RFB 003.008\n"
        await ws.send_bytes(b"hello")
        assert await ws.receive_bytes() == b"HELLO"
    # The browser left: the bridge hung up on the VNC server.
    await asyncio.wait_for(vnc_server.hung_up.wait(), 5)


async def test_vnc_without_the_subprotocol(running_app: FastAPI, vnc_server: FakeVncServer) -> None:
    async with websocket_connect(running_app, "/vnc") as ws:
        assert ws.subprotocol is None
        assert await ws.receive_bytes() == b"RFB 003.008\n"


async def test_vnc_carries_large_payloads(running_app: FastAPI, vnc_server: FakeVncServer) -> None:
    payload = bytes(range(97, 123)) * 20_000  # 520 kB: more than one read from the server
    async with websocket_connect(running_app, "/vnc", headers=SAME_SITE) as ws:
        assert await ws.receive_bytes() == b"RFB 003.008\n"
        await ws.send_bytes(payload)
        echoed = bytearray()
        while len(echoed) < len(payload):
            echoed += await ws.receive_bytes()
    assert bytes(echoed) == payload.upper()
    assert bytes(vnc_server.received) == payload


async def test_vnc_closes_with_1000_when_the_server_hangs_up(
    running_app: FastAPI, vnc_server: FakeVncServer
) -> None:
    async with websocket_connect(running_app, "/vnc", headers=SAME_SITE) as ws:
        assert await ws.receive_bytes() == b"RFB 003.008\n"
        await vnc_server.hang_up()
        with pytest.raises(WebSocketClosed) as closed:
            await ws.receive()
        assert closed.value.code == 1000


async def test_vnc_closes_with_1003_on_a_text_frame(
    running_app: FastAPI, vnc_server: FakeVncServer
) -> None:
    async with websocket_connect(running_app, "/vnc", headers=SAME_SITE) as ws:
        assert await ws.receive_bytes() == b"RFB 003.008\n"
        await ws.send_text("not RFB")
        with pytest.raises(WebSocketClosed) as closed:
            await ws.receive()
        assert closed.value.code == 1003
    await asyncio.wait_for(vnc_server.hung_up.wait(), 5)
    assert bytes(vnc_server.received) == b""
