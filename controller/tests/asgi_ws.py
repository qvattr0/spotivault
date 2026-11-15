"""An in-process WebSocket client for tests: it speaks ASGI to the app directly.

httpx's ASGITransport has no WebSockets, and Starlette's TestClient runs the app on another
thread's loop. This keeps the app on the test's own loop (debug mode and the 100 ms check apply):

    async with websocket_connect(running_app, "/api/events") as ws:
        hello = await ws.receive_json()
        ...

`WebSocketRejected` is raised when the app closes before accepting. When the app closes after
accepting, the next receive raises `WebSocketClosed` with the code.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

RECEIVE_TIMEOUT_S = 5.0


class WebSocketRejected(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"the app refused the connection (close code {code})")
        self.code = code


class WebSocketClosed(Exception):
    def __init__(self, code: int, reason: str) -> None:
        super().__init__(f"the app closed the connection: {code} {reason}")
        self.code = code
        self.reason = reason


class AsgiWebSocket:
    """The client side of one connection."""

    def __init__(
        self, to_app: asyncio.Queue, from_app: asyncio.Queue, accept: dict[str, Any]
    ) -> None:
        self._to_app = to_app
        self._from_app = from_app
        self.subprotocol: str | None = accept.get("subprotocol")
        self.close_code: int | None = None

    async def receive(self, timeout_s: float = RECEIVE_TIMEOUT_S) -> dict[str, Any]:
        """The next message the app sent, as its ASGI dict. Raises WebSocketClosed on close."""
        message = await asyncio.wait_for(self._from_app.get(), timeout_s)
        if message["type"] == "websocket.close":
            self.close_code = message.get("code", 1000)
            raise WebSocketClosed(self.close_code, message.get("reason") or "")
        return message

    async def receive_text(self, timeout_s: float = RECEIVE_TIMEOUT_S) -> str:
        message = await self.receive(timeout_s)
        if message.get("text") is None:
            raise AssertionError(f"expected a text frame, got {message!r}")
        return message["text"]

    async def receive_json(self, timeout_s: float = RECEIVE_TIMEOUT_S) -> Any:
        return json.loads(await self.receive_text(timeout_s))

    async def receive_bytes(self, timeout_s: float = RECEIVE_TIMEOUT_S) -> bytes:
        message = await self.receive(timeout_s)
        if message.get("bytes") is None:
            raise AssertionError(f"expected a binary frame, got {message!r}")
        return message["bytes"]

    async def send_text(self, text: str) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": text})

    async def send_bytes(self, data: bytes) -> None:
        await self._to_app.put({"type": "websocket.receive", "bytes": data})


@asynccontextmanager
async def websocket_connect(
    app: Any,
    path: str,
    *,
    subprotocols: Sequence[str] = (),
    headers: Sequence[tuple[str, str]] = (),
    host: str = "spotivault.test",
) -> AsyncIterator[AsgiWebSocket]:
    """Opens a WebSocket to `app` at `path`; on exit the client disconnects and the handler ends."""
    to_app: asyncio.Queue = asyncio.Queue()
    from_app: asyncio.Queue = asyncio.Queue()
    raw_headers = [(b"host", host.encode())]
    raw_headers += [(name.lower().encode(), value.encode()) for name, value in headers]
    scope = {
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
        "headers": raw_headers,
        "subprotocols": list(subprotocols),
        "state": {},
        "extensions": {},
    }
    task = asyncio.create_task(app(scope, to_app.get, from_app.put))
    await to_app.put({"type": "websocket.connect"})
    first = await asyncio.wait_for(from_app.get(), RECEIVE_TIMEOUT_S)
    if first["type"] == "websocket.close":
        await asyncio.wait_for(task, RECEIVE_TIMEOUT_S)
        raise WebSocketRejected(first.get("code", 1000))
    if first["type"] != "websocket.accept":
        task.cancel()
        raise AssertionError(f"expected websocket.accept, got {first!r}")
    ws = AsgiWebSocket(to_app, from_app, first)
    try:
        yield ws
    finally:
        await to_app.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(task, RECEIVE_TIMEOUT_S)
