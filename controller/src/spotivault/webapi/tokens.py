"""The access token: a valid one for each request, refreshed before it expires (webapi-core).

Owner: webapi-core. Only client.py uses it.

**Rules:**
- **Where the token lives:** only in the `spotify_auth` row, through the AuthStore. Never in a
  module variable that outlives a disconnect, never in a log line, never in an exception message.
- **Refresh before expiry:** when `token_expires_at` is within REFRESH_MARGIN_S, refresh first.
- **After a 401:** refresh once and retry the request; a second 401 isn't refreshed again
  (client.py does the retry).
- **One refresh at a time:** concurrent callers wait for the same refresh (a lock), and a caller
  whose stale token was already replaced uses the new one without refreshing again.
- **The refresh request:** POST accounts.spotify.com/api/token, form-encoded,
  grant_type=refresh_token, refresh_token, client_id (PKCE: no secret). Lane `auth`, through the
  scheduler, one usage row per attempt, retried on 5xx and timeouts like any call: client.py's
  `post` does all that and hands back the answer. Spotify may send a new refresh token: it's
  stored (`AuthStore.save_refreshed(refresh_token=...)`); the old one may stop working.
- **`invalid_grant`** (400): the 6-month authorization is over. Its usage row has status 400 and
  error 'invalid_grant' (client.py). `AuthStore.mark_invalid_grant()` is called (the `connection`
  event and the held runs follow from it), then ConnectionExpired is raised.
- **A reconnect during a refresh wins:** both writes name the refresh token the request used,
  and change nothing once another one is stored (auth_store.py). The caller then gets the
  token that's stored now.
- **No Client ID or no token:** NotConnected. A stored `invalid_grant_at`: ConnectionExpired,
  with no request.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta

import httpx

from spotivault.logs import redact
from spotivault.ports import (
    ApiScope,
    Clock,
    ConnectionExpired,
    NotConnected,
    WebApiError,
)
from spotivault.webapi.auth_store import AuthRow, AuthStore
from spotivault.webapi.parse import parse_token_grant

log = logging.getLogger(__name__)

REFRESH_MARGIN_S = 60

# Sends one form to the token endpoint, with the scheduler, the retries and the usage rows, and
# returns Spotify's answer (2xx or 4xx). client.py's SpotifyWebApi._post_token.
type TokenPost = Callable[[Mapping[str, str], ApiScope], Awaitable[httpx.Response]]


class TokenManager:
    """Hands out a valid access token, refreshing it when needed. See the module docstring."""

    def __init__(self, auth: AuthStore, clock: Clock, *, post: TokenPost) -> None:
        self.auth = auth
        self.clock = clock
        self._post = post
        self._lock = asyncio.Lock()  # one refresh at a time

    async def access_token(self, *, scope: ApiScope) -> str:
        """A token valid for at least REFRESH_MARGIN_S more. Raises NotConnected or
        ConnectionExpired (see the module docstring)."""
        row = await self.auth.load()
        token = _usable(row)
        if self._expiring(row):
            return await self.refresh(scope=scope)
        return token

    async def refresh(self, *, scope: ApiScope, stale_token: str | None = None) -> str:
        """Refreshes the token and returns the new one. If `stale_token` is no longer the stored
        one (another caller refreshed meanwhile), returns the stored one without a request.
        Without `stale_token` (a refresh before expiry), a token that's no longer expiring is
        returned without a request, too."""
        async with self._lock:
            row = await self.auth.load()
            token = _usable(row)
            if stale_token is not None and token != stale_token:
                return token  # another caller refreshed while we waited for the lock
            if stale_token is None and not self._expiring(row):
                return token
            return await self._refresh(row, scope)

    # --- Inside --------------------------------------------------------------------------------

    def _expiring(self, row: AuthRow) -> bool:
        if row.token_expires_at is None:
            return True
        return row.token_expires_at - self.clock.now() <= timedelta(seconds=REFRESH_MARGIN_S)

    async def _refresh(self, row: AuthRow, scope: ApiScope) -> str:
        """One refresh request, with the lock held. `row` has a token (checked by _usable)."""
        assert row.client_id is not None and row.refresh_token is not None
        used_refresh_token = row.refresh_token
        response = await self._post(
            {
                "grant_type": "refresh_token",
                "refresh_token": used_refresh_token,
                "client_id": row.client_id,
            },
            scope,
        )
        status = response.status_code
        if status == 400 and oauth_error(response) == "invalid_grant":
            marked = await self.auth.mark_invalid_grant(used_refresh_token=used_refresh_token)
            if not marked:
                # Already marked (ConnectionExpired from _usable), or a reconnect stored a new
                # token while we asked: that one is used.
                return _usable(await self.auth.load())
            raise ConnectionExpired(
                "Spotify refused the refresh token (invalid_grant): reconnect the Web API",
                status=400,
            )
        if not 200 <= status < 300:
            code = oauth_error(response) or "no error code"
            raise WebApiError(f"the token refresh was refused ({status}, {code})", status=status)
        try:
            grant = parse_token_grant(response.json(), refresh_token=used_refresh_token)
        except (ValueError, KeyError, TypeError) as exc:
            raise WebApiError(
                f"the token refresh answered something unexpected ({type(exc).__name__})",
                status=status,
            ) from None
        saved = await self.auth.save_refreshed(
            access_token=grant.access_token,
            expires_in_s=grant.expires_in_s,
            used_refresh_token=used_refresh_token,
            refresh_token=grant.refresh_token,
            scopes=grant.scopes or None,
        )
        if not saved:
            # A reconnect or a disconnect while we asked: what's stored now wins.
            return _usable(await self.auth.load())
        log.debug("Web API: access token refreshed")
        return grant.access_token


def _usable(row: AuthRow) -> str:
    """The stored access token, or the error that says why there's none to use."""
    if row.client_id is None or not row.has_token or row.access_token is None:
        raise NotConnected("not connected: connect the Web API first (wizard step 5)")
    if row.invalid_grant_at is not None:
        raise ConnectionExpired(
            "the Web API connection has expired (invalid_grant): reconnect it", status=400
        )
    return row.access_token


def oauth_error(response: httpx.Response) -> str | None:
    """The `error` code of an accounts.spotify.com error answer ("invalid_grant"), or None.
    Only the code: `error_description` is free text, so it never reaches a message."""
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, str):
        return None
    # A short, plain code; anything else isn't trusted into a message.
    return redact(error)[:64] if error.replace("_", "").isalnum() else None
