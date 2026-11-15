"""What both WebSockets share: which pages may open them, close codes, and closing quietly.

**Which pages may open them.** A browser lets any site's page open a WebSocket to any address,
the NAS's included, and sends the page's `Origin` with it. Without a check, a page from another
site could read `WS /api/events`, or see and drive the client's screen through `WS /vnc`. M1 has
no login (plan D11), so this check is what keeps the WebSockets to the controller's own pages.
The S2 stub made the same check on /vnc. Allowed (`origin_allowed`):
- **No Origin header:** not a browser (curl, the smoke test, a script on the NAS).
- **The same host and port:** the Origin's `host:port` is the request's Host header, so the page
  came from the controller itself.
- **A name in SPOTIVAULT_ALLOWED_HOSTS:** the user says it's the controller's, behind a reverse
  proxy for example, which may rewrite the Host.
- **Both on loopback:** the Origin and the Host are both `localhost`, `127.0.0.1` or `[::1]`, on any
  ports. That's the UI's Vite dev server (S7) proxying to a controller on the same machine: its
  proxy rewrites the Host (`changeOrigin`) but not the Origin. Another site's page can't have a
  loopback Origin, so only programs on the same computer get this.

Everything else is refused before the handshake (HTTP 403), `Origin: null` included (a sandboxed
frame or a local file). The same rule guards the REST requests that change something, and the Host
itself is checked first, for every request (web/guard.py).
"""

import contextlib
import ipaddress
from collections.abc import Collection
from urllib.parse import urlsplit

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketDisconnected

# Close codes (RFC 6455 § 7.4.1).
NORMAL_CLOSURE = 1000
UNSUPPORTED_DATA = 1003  # a text frame on /vnc
POLICY_VIOLATION = 1008  # another site's page (sent as HTTP 403 before the handshake)
INTERNAL_ERROR = 1011  # the hello couldn't be built
TRY_AGAIN_LATER = 1013  # too far behind, or no VNC server yet


def origin_allowed(origin: str | None, host: str, allowed_hosts: Collection[str] = ()) -> bool:
    """True when a page from `origin` may use the controller through `host` (the Host header).
    `allowed_hosts` is config.allowed_hosts (SPOTIVAULT_ALLOWED_HOSTS), in lower case."""
    if origin is None:
        return True
    try:
        page = urlsplit(origin)
        server = urlsplit("//" + host)
        page_host, server_host = page.hostname, server.hostname
    except ValueError:  # a malformed address, such as an unclosed "[::1"
        return False
    if page.scheme not in ("http", "https") or not page.netloc:
        return False
    if page.netloc.lower() == host.lower():
        return True
    if page_host is not None and page_host.rstrip(".") in allowed_hosts:
        return True
    return _is_loopback(page_host) and _is_loopback(server_host)


def websocket_origin_allowed(websocket: WebSocket) -> bool:
    """`origin_allowed` for a WebSocket's own headers and the app's config."""
    allowed_hosts = websocket.app.state.services.config.allowed_hosts
    return origin_allowed(
        websocket.headers.get("origin"), websocket.headers.get("host", ""), allowed_hosts
    )


async def accept_quietly(websocket: WebSocket, subprotocol: str | None = None) -> bool:
    """Completes the handshake. False when the client left before it could."""
    try:
        await websocket.accept(subprotocol=subprotocol)
    except (WebSocketDisconnect, WebSocketDisconnected, OSError):
        return False
    return True


async def close_quietly(websocket: WebSocket, code: int, reason: str = "") -> None:
    """Closes the socket, or refuses it before the handshake. Does nothing when the client is
    already gone: there's no one left to tell."""
    with contextlib.suppress(WebSocketDisconnect, WebSocketDisconnected, RuntimeError, OSError):
        await websocket.close(code=code, reason=reason)


def describe_client(websocket: WebSocket) -> str:
    """The client's address, for the log."""
    client = websocket.client
    return f"{client.host}:{client.port}" if client else "an unknown address"


def _is_loopback(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False
