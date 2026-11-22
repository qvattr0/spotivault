"""WS /vnc: noVNC's RFB-over-WebSocket, bridged to x11vnc on localhost (plan D9).

Only port 8080 is published, so the browser reaches the client's screen through this bridge
(wizard steps 3 and 4, the Player, and /vnc.html). It does what the S2 stub (image/stub/main.go)
did:
- **Subprotocol:** `binary` when the browser offers it (websockify's name, which noVNC and the
  smoke test send), none otherwise. Both work: the frames are binary either way.
- **Origin:** another site's page is refused before the handshake (web/sockets.py).
- **No VNC server yet:** the handshake completes, then the socket is closed with **1013** "the
  screen isn't running yet", and the page retries.
- **Bridging:** each binary frame from the browser is written to the VNC connection, and each
  chunk read from it goes back as one binary frame. noVNC reassembles RFB messages across frames,
  so the chunks need no alignment. Both directions wait for the other side to keep up.
- **Ending:** when the VNC server closes, the socket is closed with 1000; when the browser
  leaves, the VNC connection is closed. A text frame isn't RFB: it ends the bridge with **1003**,
  as the stub's NetConn did.

View-only is a noVNC setting in the page, not something this bridge enforces.
"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketDisconnected

from spotivault.services import Services
from spotivault.web.sockets import (
    NORMAL_CLOSURE,
    POLICY_VIOLATION,
    TRY_AGAIN_LATER,
    UNSUPPORTED_DATA,
    accept_quietly,
    close_quietly,
    describe_client,
    websocket_origin_allowed,
)

log = logging.getLogger(__name__)

router = APIRouter()

SUBPROTOCOL = "binary"
CHUNK = 64 * 1024  # the most read from the VNC server per frame
TCP_CLOSE_TIMEOUT_S = 5.0


class BrowserLeft(Exception):
    """The browser closed the WebSocket, or the connection dropped."""


class VncClosed(Exception):
    """The VNC server closed the connection."""


class TextFrame(Exception):
    """The browser sent a text frame. RFB is binary."""


@router.websocket("/vnc")
async def vnc(websocket: WebSocket) -> None:
    services: Services = websocket.app.state.services
    viewer = describe_client(websocket)
    if not websocket_origin_allowed(websocket):
        log.warning("vnc: refused a page from %s", websocket.headers.get("origin"))
        await close_quietly(websocket, POLICY_VIOLATION)
        return
    offered = websocket.scope.get("subprotocols") or []
    subprotocol = SUBPROTOCOL if SUBPROTOCOL in offered else None
    try:
        reader, writer = await services.ports.desktop.open_vnc()
    except OSError as exc:  # refused, or timed out (TimeoutError is an OSError)
        problem = str(exc) or type(exc).__name__
        log.info("vnc: the VNC server isn't reachable (%s); closing with 1013", problem)
        if await accept_quietly(websocket, subprotocol):
            await close_quietly(websocket, TRY_AGAIN_LATER, "the screen isn't running yet")
        return

    if not await accept_quietly(websocket, subprotocol):
        await _close_tcp(writer)
        return
    log.info("vnc: viewer connected from %s", viewer)
    close_code: int | None = NORMAL_CLOSURE  # None: the browser is gone, there's no one to tell
    close_reason = ""
    why = "the browser left"
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(_browser_to_vnc(websocket, writer))
            group.create_task(_vnc_to_browser(reader, websocket))
    except* (BrowserLeft, WebSocketDisconnect, WebSocketDisconnected):
        close_code = None
    except* (VncClosed, ConnectionError):
        why = "the VNC server closed the connection"
    except* TextFrame:
        close_code, close_reason = UNSUPPORTED_DATA, "binary frames only"
        why = "the browser sent a text frame"
    finally:
        await _close_tcp(writer)
    log.info("vnc: viewer from %s left: %s", viewer, why)
    if close_code is not None:
        await close_quietly(websocket, close_code, close_reason)


async def _browser_to_vnc(websocket: WebSocket, writer: asyncio.StreamWriter) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise BrowserLeft
        data = message.get("bytes")
        if data is None:
            raise TextFrame
        writer.write(data)
        await writer.drain()  # raises ConnectionError if the VNC server went away


async def _vnc_to_browser(reader: asyncio.StreamReader, websocket: WebSocket) -> None:
    while True:
        data = await reader.read(CHUNK)
        if not data:
            raise VncClosed
        await websocket.send_bytes(data)


async def _close_tcp(writer: asyncio.StreamWriter) -> None:
    """Closes the VNC connection; aborts it if what's left to send can't be flushed in time."""
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), TCP_CLOSE_TIMEOUT_S)
    except OSError:  # TimeoutError included
        writer.transport.abort()
