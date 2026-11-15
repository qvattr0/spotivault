"""WS /api/events: the live event stream (contracts/events.md).

Each connection gets:
1. **`hello` first:** the snapshot built from every provider modules registered with
   `services.bus.add_snapshot`. Its `seq` is the last event published before the connection
   subscribed, and every later event follows it in order, with no gaps (events.py).
2. **Then every event,** one JSON text frame each. What the client sends is read and ignored.

How a connection ends:
- **The client leaves:** the handler notices at once (it always waits for the client's next
  message) and drops its subscription.
- **A slow client:** 256 unsent events, then the bus drops the subscription and the socket is
  closed with **1013** ("try again later"). The client reconnects and gets a fresh `hello`.
  uvicorn holds back a send while the client's TCP buffer is full, so a client that stops
  reading fills those 256 instead of the controller's memory.
- **The hello can't be built** (a provider failed, or the database isn't open): closed with
  **1011** after the handshake, and the error is logged. The client retries with its backoff.
- **The controller stops:** uvicorn closes every socket with **1012** ("service restart").
- **Another site's page:** refused before the handshake (web/sockets.py).

Keep-alive pings every 20 s come from uvicorn (`ws_ping_interval` in __main__.py); a client that
doesn't answer within 20 s is closed with 1011. uvicorn also answers the client's own pings.
"""

import asyncio
import contextlib
import logging

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketDisconnected

from spotivault.events import Subscription, SubscriptionOverflow
from spotivault.services import Services
from spotivault.web.sockets import (
    INTERNAL_ERROR,
    POLICY_VIOLATION,
    TRY_AGAIN_LATER,
    accept_quietly,
    close_quietly,
    describe_client,
    websocket_origin_allowed,
)

log = logging.getLogger(__name__)

router = APIRouter()


class ClientLeft(Exception):
    """The client closed the socket, or the connection dropped."""


@router.websocket("/api/events")
async def events(websocket: WebSocket) -> None:
    services: Services = websocket.app.state.services
    client = describe_client(websocket)
    if not websocket_origin_allowed(websocket):
        log.warning("events: refused a page from %s", websocket.headers.get("origin"))
        await close_quietly(websocket, POLICY_VIOLATION)
        return
    if not await accept_quietly(websocket):
        return
    async with contextlib.AsyncExitStack() as stack:
        try:
            sub = await stack.enter_async_context(services.bus.subscribe())
        except Exception:
            log.exception("events: the hello snapshot failed; closing the connection with 1011")
            await close_quietly(websocket, INTERNAL_ERROR, "no snapshot yet; reconnect")
            return
        log.debug("events: %s connected (%d open)", client, services.bus.subscriber_count)
        await _stream(websocket, sub)
    log.debug("events: %s left (%d open)", client, services.bus.subscriber_count)


async def _stream(websocket: WebSocket, sub: Subscription) -> None:
    """Sends the hello, then every event, until the client leaves or falls too far behind."""
    assert sub.hello is not None  # subscribe() builds it before handing the subscription over
    try:
        await websocket.send_text(sub.hello.to_json())
        async with asyncio.TaskGroup() as group:
            group.create_task(_send_events(websocket, sub))
            group.create_task(_wait_for_close(websocket))
    except* (ClientLeft, WebSocketDisconnect, WebSocketDisconnected):
        pass
    except* SubscriptionOverflow:
        # events.py has logged it. The close frame goes out once the client reads what's queued.
        await close_quietly(websocket, TRY_AGAIN_LATER, "too far behind; reconnect")


async def _send_events(websocket: WebSocket, sub: Subscription) -> None:
    while True:
        event = await sub.next()  # raises SubscriptionOverflow
        await websocket.send_text(event.to_json())


async def _wait_for_close(websocket: WebSocket) -> None:
    """Reads (and ignores) what the client sends, until it disconnects."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise ClientLeft
