"""Both WebSockets behind a real uvicorn, as __main__.py runs it (h11, wsproto, pings), on a
loopback port of its own. What tests/asgi_ws.py can't show: the HTTP upgrade and the
subprotocol header, WebSocket pings, refusing with 403, and closing with 1012 at shutdown.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from wsproto import ConnectionType, WSConnection
from wsproto import events as ws
from wsproto.connection import ConnectionState

from spotivault import __main__ as main
from spotivault.services import Services

PING_INTERVAL_S = 0.2
TIMEOUT_S = 5.0


@dataclass
class RunningServer:
    server: uvicorn.Server
    task: "asyncio.Task[None]"

    @property
    def port(self) -> int:
        return self.server.servers[0].sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self.server.should_exit = True
        await asyncio.wait_for(self.task, TIMEOUT_S)


@pytest.fixture
def uvicorn_config(app: FastAPI) -> Iterator[uvicorn.Config]:
    """__main__.py's settings, with quick pings, an ephemeral port, and no lifespan (the test's
    `running_app` runs it). Loaded here, outside the loop: loading takes a while."""
    config = main.uvicorn_config(
        app,
        host="127.0.0.1",
        port=0,
        ping_interval_s=PING_INTERVAL_S,
        ping_timeout_s=PING_INTERVAL_S * 3,
        graceful_shutdown_s=3,
        lifespan="off",
    )
    config.load()
    yield config


@pytest.fixture
async def server(
    running_app: FastAPI, uvicorn_config: uvicorn.Config
) -> AsyncIterator[RunningServer]:
    server = uvicorn.Server(uvicorn_config)
    task = asyncio.create_task(server.serve())
    for _ in range(int(TIMEOUT_S / 0.01)):
        if server.started or task.done():
            break
        await asyncio.sleep(0.01)
    assert server.started, "uvicorn didn't start"
    running = RunningServer(server, task)
    yield running
    if not task.done():
        await running.stop()


class RawWebSocket:
    """A WebSocket client on a real TCP connection, with wsproto. It answers pings unless told
    not to, and counts them."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.conn = WSConnection(ConnectionType.CLIENT)
        self.pending: list[ws.Event] = []
        self.answer_pings = True
        self.pings = 0
        self.subprotocol: str | None = None
        self._text: list[str] = []
        self._bytes = bytearray()

    @classmethod
    async def open(
        cls,
        port: int,
        path: str,
        *,
        subprotocols: Sequence[str] = (),
        origin: str | None = None,
        host: str | None = None,
    ) -> "RawWebSocket":
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        client = cls(reader, writer)
        headers = [(b"origin", origin.encode())] if origin else []
        request = ws.Request(
            host=host or f"127.0.0.1:{port}",
            target=path,
            subprotocols=list(subprotocols),
            extra_headers=headers,
        )
        client._send(request)
        return client

    async def handshake(self) -> ws.Event:
        """The server's answer to the upgrade: AcceptConnection or RejectConnection."""
        event = await self.next_event()
        if isinstance(event, ws.AcceptConnection):
            self.subprotocol = event.subprotocol
        return event

    async def message(self) -> str | bytes | ws.CloseConnection:
        """The next whole message, or the server's close."""
        while True:
            event = await self.next_event()
            if isinstance(event, ws.CloseConnection):
                return event
            if isinstance(event, ws.TextMessage):
                self._text.append(event.data)
                if event.message_finished:
                    text, self._text = "".join(self._text), []
                    return text
            if isinstance(event, ws.BytesMessage):
                self._bytes += event.data
                if event.message_finished:
                    data, self._bytes = bytes(self._bytes), bytearray()
                    return data

    async def next_event(self) -> ws.Event:
        while not self.pending:
            data = await asyncio.wait_for(self.reader.read(65536), TIMEOUT_S)
            self._feed(data)
        return self.pending.pop(0)

    async def idle(self, seconds: float) -> None:
        """Reads for `seconds`, answering pings; other events wait in `pending`."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        while (left := deadline - loop.time()) > 0:
            try:
                data = await asyncio.wait_for(self.reader.read(65536), left)
            except TimeoutError:
                return
            self._feed(data)

    def _feed(self, data: bytes) -> None:
        if not data:
            raise ConnectionError("the server closed the TCP connection")
        self.conn.receive_data(data)
        for event in self.conn.events():
            if isinstance(event, ws.Ping):
                self.pings += 1
                if self.answer_pings and self.conn.state == ConnectionState.OPEN:
                    self._send(event.response())
                continue
            self.pending.append(event)

    def send_bytes(self, data: bytes) -> None:
        self._send(ws.Message(data=data))

    def close(self, code: int = 1000) -> None:
        self._send(ws.CloseConnection(code=code))

    async def aclose(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()

    def _send(self, event: Any) -> None:
        self.writer.write(self.conn.send(event))


async def test_events_over_a_real_server(server: RunningServer, services: Services) -> None:
    client = await RawWebSocket.open(server.port, "/api/events")
    assert isinstance(await client.handshake(), ws.AcceptConnection)
    assert client.subprotocol is None
    hello = json.loads(await client.message())  # type: ignore[arg-type]
    assert hello["type"] == "hello"
    services.bus.publish("connection", {"mark": 1})
    while True:
        event = json.loads(await client.message())  # type: ignore[arg-type]
        if event["data"].get("mark") == 1:
            break
    # Pings keep the connection alive while nothing happens; the client answers them.
    await client.idle(PING_INTERVAL_S * 4)
    assert client.pings >= 2
    assert not client.pending  # still open
    client.close()
    reply = await client.message()
    assert isinstance(reply, ws.CloseConnection) and reply.code == 1000
    await client.aclose()
    for _ in range(100):
        if services.bus.subscriber_count == 0:
            break
        await asyncio.sleep(0.01)
    assert services.bus.subscriber_count == 0


async def test_a_client_that_ignores_pings_is_closed(server: RunningServer) -> None:
    client = await RawWebSocket.open(server.port, "/api/events")
    client.answer_pings = False
    assert isinstance(await client.handshake(), ws.AcceptConnection)
    await client.message()  # hello
    closed = await client.message()
    assert isinstance(closed, ws.CloseConnection) and closed.code == 1011
    await client.aclose()


async def test_shutdown_closes_with_1012(server: RunningServer, services: Services) -> None:
    client = await RawWebSocket.open(server.port, "/api/events")
    assert isinstance(await client.handshake(), ws.AcceptConnection)
    await client.message()  # hello
    stopping = asyncio.create_task(server.stop())
    closed = await client.message()
    assert isinstance(closed, ws.CloseConnection) and closed.code == 1012
    await asyncio.wait_for(stopping, TIMEOUT_S)  # the handler ended: no 30 s wait
    await client.aclose()
    assert services.bus.subscriber_count == 0


async def test_another_sites_page_gets_403(server: RunningServer) -> None:
    for path in ("/api/events", "/vnc"):
        client = await RawWebSocket.open(server.port, path, origin="https://evil.example")
        answer = await client.handshake()
        assert isinstance(answer, ws.RejectConnection) and answer.status_code == 403, path
        await client.aclose()


async def test_a_rebound_name_gets_403(server: RunningServer) -> None:
    # DNS rebinding: the page's Origin matches the Host, an attacker's name for the NAS's address.
    rebound = f"rebind.attacker.example:{server.port}"
    for path in ("/api/events", "/vnc"):
        client = await RawWebSocket.open(
            server.port, path, origin=f"http://{rebound}", host=rebound
        )
        answer = await client.handshake()
        assert isinstance(answer, ws.RejectConnection) and answer.status_code == 403, path
        await client.aclose()


async def test_the_vite_dev_server_on_loopback_is_allowed(server: RunningServer) -> None:
    client = await RawWebSocket.open(server.port, "/api/events", origin="http://localhost:5173")
    assert isinstance(await client.handshake(), ws.AcceptConnection)
    await client.aclose()


async def test_vnc_handshake_as_the_smoke_test_does(
    server: RunningServer, services: Services
) -> None:
    async def greet(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"RFB 003.008\n")
        await writer.drain()
        while data := await reader.read(1024):
            writer.write(data[::-1])
            await writer.drain()
        writer.close()

    vnc = await asyncio.start_server(greet, "127.0.0.1", 0)
    vnc_port = vnc.sockets[0].getsockname()[1]

    async def open_vnc() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_connection("127.0.0.1", vnc_port)

    services.ports.desktop.open_vnc = open_vnc  # type: ignore[method-assign]
    try:
        client = await RawWebSocket.open(server.port, "/vnc", subprotocols=["binary"])
        assert isinstance(await client.handshake(), ws.AcceptConnection)
        assert client.subprotocol == "binary"
        assert await client.message() == b"RFB 003.008\n"
        client.send_bytes(b"abc")
        assert await client.message() == b"cba"
        client.close()
        reply = await client.message()
        assert isinstance(reply, ws.CloseConnection)
        await client.aclose()
    finally:
        vnc.close()
        await vnc.wait_closed()


async def test_vnc_without_a_server_closes_with_1013(server: RunningServer) -> None:
    client = await RawWebSocket.open(server.port, "/vnc", subprotocols=["binary"])
    assert isinstance(await client.handshake(), ws.AcceptConnection)
    closed = await client.message()
    assert isinstance(closed, ws.CloseConnection) and closed.code == 1013
    await client.aclose()
