"""Which requests the controller serves at all: the Host and Origin checks (`RequestGuard`).

M1 has no login (plan D11), and a browser lets any site's page send requests to the NAS's
address. These two checks, run on every request before routing (app.py), keep other sites' pages
away from the API, the event stream and the client's screen:

- **Host**, on every HTTP request and WebSocket (`host_allowed`). A page can make its own name
  resolve to the NAS's address (DNS rebinding). Its requests then carry that name as Host, and
  its Origin matches it, so the Origin check alone would let it read the API and drive `WS /vnc`.
  So the Host must be a name the public DNS can't hand out:
  - an IP address, `localhost` or a name ending in `.localhost`;
  - a name with no dot (`nas`), or one ending in `.local`, `.lan`, `.internal` or `.home.arpa`;
  - or a name in SPOTIVAULT_ALLOWED_HOSTS (config.allowed_hosts): your own domain, or a reverse
    proxy's name.
- **Origin**, on POST, PUT, PATCH and DELETE. A page from another site can send a form, or a
  `no-cors` fetch, without reading the answer. A request whose Origin is another site's is
  refused, by the same rule as the WebSockets' (`sockets.origin_allowed`). GET, HEAD and OPTIONS
  change nothing, and the WebSockets check Origin themselves.

A request with no Host or no Origin header isn't from a browser (curl, the smoke test, the
healthcheck), so that check passes. A refused request gets 403 `forbidden`. A refused WebSocket is
closed before its handshake, which the client sees as HTTP 403 too. Each new refusal is logged
once, with the setting that would allow it.
"""

import ipaddress
import logging
from collections.abc import Collection
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from spotivault.errors import ApiError, error_response
from spotivault.web.sockets import POLICY_VIOLATION, close_quietly, origin_allowed

log = logging.getLogger(__name__)

# Names the public DNS never hands out: mDNS, private-use and home-router names, and loopback.
PRIVATE_SUFFIXES = (".local", ".lan", ".internal", ".home.arpa", ".localhost")
CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MAX_LOGGED = 100  # refusals remembered, so each is logged once and a flood can't grow the set


def host_allowed(host: str, allowed_hosts: Collection[str] = ()) -> bool:
    """True when `host` (a Host header: a name or an address, maybe with a port) is a name the
    controller answers to. `allowed_hosts` is config.allowed_hosts, in lower case."""
    try:
        name = urlsplit("//" + host).hostname  # lower case, without the port or brackets
    except ValueError:  # a malformed address, such as an unclosed "[::1"
        return False
    name = (name or "").rstrip(".")
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    if name == "localhost" or "." not in name or name.endswith(PRIVATE_SUFFIXES):
        return True
    return name in allowed_hosts


class RequestGuard:
    """ASGI middleware: the Host check on every HTTP request and WebSocket, and the Origin check
    on requests that change something. Everything else (lifespan) passes straight through."""

    def __init__(self, app: ASGIApp, allowed_hosts: Collection[str] = ()) -> None:
        self.app = app
        self.allowed_hosts = frozenset(allowed_hosts)
        self._logged: set[str] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            problem = self.problem(scope)
            if problem is not None:
                await self._refuse(scope, receive, send, problem)
                return
        await self.app(scope, receive, send)

    def problem(self, scope: Scope) -> str | None:
        """Why the request is refused, in English for the log, or None to serve it."""
        headers = Headers(scope=scope)
        host = headers.get("host")
        if host is not None and not host_allowed(host, self.allowed_hosts):
            return (
                f"the address {host!r} isn't a name for this NAS on a home network; "
                "to reach spotivault by that name, add it to SPOTIVAULT_ALLOWED_HOSTS"
            )
        if scope["type"] == "http" and scope["method"] in CHANGING_METHODS:
            origin = headers.get("origin")
            if not origin_allowed(origin, host or "", self.allowed_hosts):
                return f"a page from {origin!r} can't change anything here"
        return None

    async def _refuse(self, scope: Scope, receive: Receive, send: Send, problem: str) -> None:
        if problem not in self._logged and len(self._logged) < MAX_LOGGED:
            self._logged.add(problem)
            what = "WebSocket" if scope["type"] == "websocket" else scope["method"]
            log.warning("refused %s %s: %s", what, scope["path"], problem)
        if scope["type"] == "websocket":
            await close_quietly(WebSocket(scope, receive, send), POLICY_VIOLATION)
            return
        response = error_response(ApiError(403, "forbidden", f"Refused: {problem}."))
        await response(scope, receive, send)
