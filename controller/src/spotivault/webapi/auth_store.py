"""The Web API connection as stored: the one `spotify_auth` row (contracts/schema.sql).

It holds the Client ID, the tokens, who they belong to, and the 6-month expiry. The database file
is mode 0600, and the tokens never leave it except in the Authorization header and the refresh
form: AuthRow keeps them out of its repr, so a log line or a traceback can't show them.

Who writes what:

| Call | By | When |
|---|---|---|
| `set_client_id` | spotify-connect | POST /api/spotify/app. A different id deletes the token. |
| `save_grant`, `set_account` | spotify-connect | After the code exchange, then GET /me. |
| `save_refreshed` | webapi-core | After a refresh. Not a connection change: no listener is told. |
| `mark_invalid_grant` | webapi-core (and the fake Web API) | Spotify answered `invalid_grant`. |

**A refresh races a reconnect:** the refresh request can take a while (retries wait outside any
lock), and step 5 can store a new authorization meanwhile. So `save_refreshed` and
`mark_invalid_grant` take the refresh token the request used, and write only while that is still
the stored one: the check and the write are one statement. Otherwise the new connection stands.
| `disconnect` | spotify-connect | DELETE /api/spotify/connection. |

Listeners (`add_listener`) are awaited after each change but `save_refreshed`, once it's
committed: ConnectionService publishes the `connection` event from there.
"""

import calendar
import json
import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from spotivault.clock import iso_ms, parse_iso
from spotivault.ports import Clock, SpotifyUser, TokenGrant
from spotivault.store import Store

log = logging.getLogger(__name__)

AUTHORIZATION_MONTHS = 6  # a refresh token works for 6 months after you authorize (mid-2026)
EXPIRING_WITHIN = timedelta(weeks=4)  # the yellow banner, and `expiring`
CLIENT_ID = re.compile(r"[0-9a-f]{32}")

# openapi.yaml Connection.state
type ConnectionState = Literal["not_configured", "disconnected", "ok", "expiring", "expired"]
# What changed, for listeners.
type AuthChange = Literal["client_id", "connected", "account", "expired", "disconnected"]
type AuthListener = Callable[[AuthChange], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class AuthRow:
    """The `spotify_auth` row. Every field is None (scopes empty) when there's no row yet."""

    client_id: str | None = None
    access_token: str | None = field(default=None, repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    token_expires_at: datetime | None = None  # the access token's own ~1 h expiry
    scopes: tuple[str, ...] = ()
    user_id: str | None = None
    display_name: str | None = None
    authorized_at: datetime | None = None
    expires_at: datetime | None = None  # authorized_at + 6 months; refreshing never moves it
    invalid_grant_at: datetime | None = None

    @property
    def has_token(self) -> bool:
        return self.access_token is not None and self.refresh_token is not None

    def state(self, now: datetime) -> ConnectionState:
        """openapi.yaml Connection.state: `expired` once Spotify said `invalid_grant` or
        `expires_at` has passed, `expiring` within 4 weeks of it."""
        if self.client_id is None:
            return "not_configured"
        if not self.has_token:
            return "disconnected"
        if self.invalid_grant_at is not None:
            return "expired"
        if self.expires_at is not None:
            if now >= self.expires_at:
                return "expired"
            if now >= self.expires_at - EXPIRING_WITHIN:
                return "expiring"
        return "ok"

    @property
    def client_id_masked(self) -> str | None:
        """The first and last 4 characters, for the UI: '0123…cdef'."""
        return mask_client_id(self.client_id)


def mask_client_id(client_id: str | None) -> str | None:
    if client_id is None:
        return None
    return f"{client_id[:4]}…{client_id[-4:]}"


def add_months(moment: datetime, months: int) -> datetime:
    """`moment` plus whole calendar months, on the same day or the month's last day:
    12 Nov 2026 + 6 → 12 May 2027; 31 Aug 2026 + 6 → 28 Feb 2027."""
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


class AuthStore:
    """Reads and writes the `spotify_auth` row (id = 1). One instance per controller:
    services.py makes it and hands it to the real port, the fake one and `services.auth`."""

    def __init__(self, store: Store, clock: Clock) -> None:
        self.store = store
        self.clock = clock
        self._listeners: list[AuthListener] = []

    def add_listener(self, fn: AuthListener) -> None:
        """`fn(change)` is awaited after each committed change except a token refresh. A listener
        that raises is logged; the change stands, and the other listeners still run."""
        self._listeners.append(fn)

    async def load(self) -> AuthRow:
        row = await self.store.fetchone("SELECT * FROM spotify_auth WHERE id = 1")
        if row is None:
            return AuthRow()
        return AuthRow(
            client_id=row["client_id"],
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            token_expires_at=_time(row["token_expires_at"]),
            scopes=tuple(json.loads(row["scopes"])) if row["scopes"] else (),
            user_id=row["user_id"],
            display_name=row["display_name"],
            authorized_at=_time(row["authorized_at"]),
            expires_at=_time(row["expires_at"]),
            invalid_grant_at=_time(row["invalid_grant_at"]),
        )

    async def set_client_id(self, client_id: str) -> bool:
        """Stores the Client ID (32 lowercase hex digits; ValueError otherwise). A different id
        than the stored one disconnects: the token and the account facts are deleted. Returns
        True when the id changed."""
        if CLIENT_ID.fullmatch(client_id) is None:
            raise ValueError("a Client ID is 32 lowercase hex digits")
        now = iso_ms(self.clock.now())

        def write(conn: sqlite3.Connection) -> bool:
            row = conn.execute("SELECT client_id FROM spotify_auth WHERE id = 1").fetchone()
            if row is not None and row["client_id"] == client_id:
                return False
            if row is None:
                conn.execute(
                    "INSERT INTO spotify_auth (id, client_id, updated_at) VALUES (1, ?, ?)",
                    (client_id, now),
                )
            else:
                conn.execute(
                    f"UPDATE spotify_auth SET client_id = ?, {_NO_TOKEN}, updated_at = ? "
                    "WHERE id = 1",
                    (client_id, now),
                )
            return True

        changed = await self.store.transaction(write)
        if changed:
            await self._notify("client_id")
        return changed

    async def save_grant(self, client_id: str, grant: TokenGrant) -> AuthRow:
        """Stores a new authorization: the tokens, their scopes, `authorized_at` now and
        `expires_at` 6 months on. It clears `invalid_grant_at` and the account facts (call
        `set_account` next, after GET /me). Reconnecting resets the 6-month clock."""
        if CLIENT_ID.fullmatch(client_id) is None:
            raise ValueError("a Client ID is 32 lowercase hex digits")
        now = self.clock.now()
        values = (
            client_id,
            grant.access_token,
            grant.refresh_token,
            iso_ms(now + timedelta(seconds=grant.expires_in_s)),
            json.dumps(list(grant.scopes)),
            iso_ms(now),
            iso_ms(add_months(now, AUTHORIZATION_MONTHS)),
            iso_ms(now),
        )

        def write(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO spotify_auth (id, client_id, access_token, refresh_token, "
                "token_expires_at, scopes, user_id, display_name, authorized_at, expires_at, "
                "invalid_grant_at, updated_at) "
                "VALUES (1, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, ?) "
                "ON CONFLICT (id) DO UPDATE SET client_id = excluded.client_id, "
                "access_token = excluded.access_token, refresh_token = excluded.refresh_token, "
                "token_expires_at = excluded.token_expires_at, scopes = excluded.scopes, "
                "user_id = NULL, display_name = NULL, authorized_at = excluded.authorized_at, "
                "expires_at = excluded.expires_at, invalid_grant_at = NULL, "
                "updated_at = excluded.updated_at",
                values,
            )

        await self.store.transaction(write)
        await self._notify("connected")
        return await self.load()

    async def set_account(self, user: SpotifyUser) -> None:
        """Stores who the token belongs to (GET /me): "Connected as <display name>"."""
        result = await self.store.execute(
            "UPDATE spotify_auth SET user_id = ?, display_name = ?, updated_at = ? WHERE id = 1",
            (user.id, user.display_name, iso_ms(self.clock.now())),
        )
        if result.rowcount:
            await self._notify("account")

    async def save_refreshed(
        self,
        *,
        access_token: str,
        expires_in_s: int,
        used_refresh_token: str,
        refresh_token: str | None = None,
        scopes: Sequence[str] | None = None,
    ) -> bool:
        """Stores a refreshed access token, and the new refresh token when Spotify sent one,
        but only while `used_refresh_token` (the one the refresh sent) is still stored: a
        reconnect or a disconnect meanwhile wins. Returns True when it was stored.
        `expires_at` doesn't move: refreshing never extends the authorization. Listeners aren't
        told; nothing the UI shows changed."""
        now = self.clock.now()
        result = await self.store.execute(
            "UPDATE spotify_auth SET access_token = ?, refresh_token = coalesce(?, refresh_token), "
            "token_expires_at = ?, scopes = coalesce(?, scopes), updated_at = ? "
            "WHERE id = 1 AND access_token IS NOT NULL AND refresh_token = ?",
            (
                access_token,
                refresh_token,
                iso_ms(now + timedelta(seconds=expires_in_s)),
                json.dumps(list(scopes)) if scopes is not None else None,
                iso_ms(now),
                used_refresh_token,
            ),
        )
        return result.rowcount > 0

    async def mark_invalid_grant(self, *, used_refresh_token: str | None = None) -> bool:
        """Spotify answered `invalid_grant`: the connection is `expired` until you reconnect,
        and scheduled runs are held. With `used_refresh_token` (the one Spotify refused), only
        while that is still stored: a reconnect meanwhile isn't marked. Returns True for the
        first mark, which notifies; the token is kept, so the UI can still show who was
        connected."""
        now = iso_ms(self.clock.now())
        sql = (
            "UPDATE spotify_auth SET invalid_grant_at = ?, updated_at = ? "
            "WHERE id = 1 AND access_token IS NOT NULL AND invalid_grant_at IS NULL"
        )
        params: tuple[str, ...] = (now, now)
        if used_refresh_token is not None:
            sql += " AND refresh_token = ?"
            params += (used_refresh_token,)
        result = await self.store.execute(sql, params)
        if not result.rowcount:
            return False
        log.warning("Web API: Spotify refused the refresh token (invalid_grant): reconnect")
        await self._notify("expired")
        return True

    async def disconnect(self) -> None:
        """Deletes the token and the account facts. The Client ID is kept."""
        result = await self.store.execute(
            f"UPDATE spotify_auth SET {_NO_TOKEN}, updated_at = ? "
            "WHERE id = 1 AND access_token IS NOT NULL",
            (iso_ms(self.clock.now()),),
        )
        if result.rowcount:
            await self._notify("disconnected")

    async def _notify(self, change: AuthChange) -> None:
        for fn in list(self._listeners):
            try:
                await fn(change)
            except Exception:
                log.exception("a Web API connection listener failed (%s)", change)


# Every column but the Client ID back to "no connection".
_NO_TOKEN = (
    "access_token = NULL, refresh_token = NULL, token_expires_at = NULL, scopes = NULL, "
    "user_id = NULL, display_name = NULL, authorized_at = NULL, expires_at = NULL, "
    "invalid_grant_at = NULL"
)


def _time(text: str | None) -> datetime | None:
    return parse_iso(text.replace("Z", "+00:00")) if text else None
