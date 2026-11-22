"""The Web API connection: wizard step 5, the expiry banner, Settings › Spotify account.

Owner: spotify-connect. Specs: web-ui.md § 5 and § Spotify account (Web API), openapi.yaml tag
`spotify`, events.md `connection`. Built by services.py as `services.connection`.

Frozen for other modules and S6: `connection()`, `held_reason()` and `our_device()`.

**What it does:**
- **The connection** (`connection()`, GET /api/spotify/connection, the hello's `connection` key,
  the `connection` event): built from `services.auth.load()` and `services.clock.now()`:
  `AuthRow.state(now)`, the display name, user id, masked Client ID, `authorized_at`,
  `expires_at` (authorized_at + 6 months) and the scopes.
- **Events:** publish `connection` after every connection change: an AuthStore listener
  (`services.auth.add_listener`) covers the Client ID, a new grant, the account, `invalid_grant`
  (marked by the port, real or fake) and a disconnect. A background task publishes it again when
  the state crosses a time boundary: `expiring` 4 weeks before `expires_at`, `expired` at it.
- **Client ID** (POST /api/spotify/app): `AuthStore.set_client_id`; a different id disconnects.
  409 `run_active` during a run (the `runs` table has a row with kind 'run' and state <> 'ended',
  as setup.py's `_run_is_active`).
- **Authorize** (POST /api/spotify/auth/start): 409 `no_client_id` without one. Deletes expired
  `pkce_pending` rows and replaces any pending one (one at a time), stores the new state,
  verifier and Client ID for 15 minutes, and returns the authorize URL (pkce.py).
- **Finish** (POST /api/spotify/auth/finish, `{redirect_url}`): 422 with `invalid_redirect`,
  `access_denied`, `no_pending_auth` (none pending, or expired) or `state_mismatch` (a pending one
  exists, with another state). Then `ports.webapi.exchange_code(..., scope=SETUP)` (422
  `token_exchange_failed` when refused), delete the pending row (single use),
  `AuthStore.save_grant`, GET /me (`set_account`), and the device check below. Then ask for a
  catalog refresh (`services.catalog.request_refresh("setup")`) so step 7 can count playlists.
  Returns the connection. Reconnecting resets the 6-month clock. Nothing secret is logged.
- **Devices** (GET /api/spotify/devices): one `devices()` call; `ours` is `our_device()`.
  Step 5 turns done (`services.setup.mark_done("webapi")`) only when the token works AND our
  device is listed; with the token working but no device, `mark_failed("webapi", "Make sure the
  client in step 3 is open and logged in.")`. Both are no-ops once setup is complete.
- **Disconnect** (DELETE /api/spotify/connection): 409 `run_active` during a run;
  `AuthStore.disconnect()` (the Client ID stays). Scheduled runs are held until you reconnect.
- **Held runs** (`held_reason()`, for S6 and GET /api/schedule/next): `connection_expired` while
  the state is `expired`, `not_connected` while it's `not_configured` or `disconnected`, else
  None. `expiring` isn't held.

Registered in the constructor: the hello's snapshot (`snapshot()`, which never raises), the
AuthStore listener and the boundary task (`services.add_background("connection.watch", ...)`).
"""

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from spotivault.api.models import AuthStart, Connection, Devices
from spotivault.api.models import Device as DeviceModel
from spotivault.clock import iso_ms, parse_iso
from spotivault.errors import ApiError, run_active
from spotivault.ports import SETUP, Device, TokenExchangeFailed, WebApiError
from spotivault.webapi.auth_store import EXPIRING_WITHIN, AuthChange, AuthRow
from spotivault.webapi.endpoints import REDIRECT_URI
from spotivault.webapi.pkce import (
    InvalidRedirect,
    authorize_url,
    new_pkce,
    new_state,
    parse_redirect,
)

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

PKCE_TTL_S = 15 * 60
# The longest the boundary watcher sleeps at a time, so a change it doesn't hear about is
# noticed within the hour.
WATCH_MAX_S = 3600.0
DEVICE_MISSING = "Make sure the client in step 3 is open and logged in."

type HeldReason = Literal["connection_expired", "not_connected"]


def our_device(devices: list[Device], device_name: str) -> Device | None:
    """The container's Connect device: the first one named `device_name`, ignoring case. Other
    computers on the account are listed too, and never picked (probe.py `pick_device`)."""
    wanted = device_name.casefold()
    for device in devices:
        if device.name.casefold() == wanted:
            return device
    return None


@dataclass(frozen=True, slots=True)
class _Pending:
    """A claimed PKCE authorization: the verifier and the Client ID it was started with."""

    state: str
    code_verifier: str
    client_id: str


def _connection(row: AuthRow, now: datetime) -> Connection:
    """The API shape of the stored connection, as of `now`."""
    return Connection(
        state=row.state(now),
        display_name=row.display_name,
        user_id=row.user_id,
        client_id_masked=row.client_id_masked,
        authorized_at=row.authorized_at,
        expires_at=row.expires_at,
        scopes=list(row.scopes),
    )


def _device_model(device: Device) -> DeviceModel:
    return DeviceModel(id=device.id, name=device.name, type=device.type, is_active=device.is_active)


def _next_boundary(row: AuthRow, now: datetime) -> datetime | None:
    """The next moment the state changes with time alone: `expiring`, then `expired`. None when
    there's no authorization to expire, or it's expired already."""
    if not row.has_token or row.invalid_grant_at is not None or row.expires_at is None:
        return None
    expiring_at = row.expires_at - EXPIRING_WITHIN
    if now < expiring_at:
        return expiring_at
    if now < row.expires_at:
        return row.expires_at
    return None


def _time(text: str) -> datetime:
    return parse_iso(text.replace("Z", "+00:00"))


class ConnectionService:
    """The Web API connection. See the module docstring."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        services.bus.add_snapshot("connection", self.snapshot)
        services.auth.add_listener(self._on_change)
        services.add_background("connection.watch", self.watch)

    async def connection(self) -> Connection:
        """The connection now: GET /api/spotify/connection, the hello and the event."""
        row = await self.services.auth.load()
        return _connection(row, self.services.clock.now())

    async def snapshot(self) -> Connection:
        """The WS hello's `connection`. Never raises: when the database can't be read, it's
        "not configured" (the hello must still work, as setup's snapshot does)."""
        try:
            return await self.connection()
        except Exception:
            log.exception("connection: can't read the Web API connection for the hello")
            return _connection(AuthRow(), self.services.clock.now())

    async def held_reason(self) -> HeldReason | None:
        """Why scheduled runs are held by the connection, or None (S6)."""
        row = await self.services.auth.load()
        state = row.state(self.services.clock.now())
        if state == "expired":
            return "connection_expired"
        if state in ("not_configured", "disconnected"):
            return "not_connected"
        return None

    async def set_client_id(self, client_id: str) -> Connection:
        """POST /api/spotify/app. A different id than the stored one disconnects."""
        await self._refuse_during_run()
        try:
            await self.services.auth.set_client_id(client_id)
        except ValueError as exc:
            raise ApiError(422, "validation_failed", str(exc), {"field": "client_id"}) from exc
        return await self.connection()

    async def start_auth(self) -> AuthStart:
        """POST /api/spotify/auth/start: stores a new PKCE attempt and returns the authorize URL.

        The verifier is stored, never returned. The Client ID is read in the same transaction,
        so an attempt can't outlive a change of the Client ID.
        """
        verifier = new_pkce()
        state = new_state()
        now = self.services.clock.now()
        expires = now + timedelta(seconds=PKCE_TTL_S)

        def write(conn: sqlite3.Connection) -> str:
            stored = conn.execute("SELECT client_id FROM spotify_auth WHERE id = 1").fetchone()
            if stored is None or stored["client_id"] is None:
                raise ApiError(409, "no_client_id", "Store the developer app's Client ID first.")
            conn.execute("DELETE FROM pkce_pending")  # expired rows, and any pending one
            conn.execute(
                "INSERT INTO pkce_pending (state, code_verifier, client_id, created_at, expires_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (state, verifier.verifier, stored["client_id"], iso_ms(now), iso_ms(expires)),
            )
            return str(stored["client_id"])

        client_id = await self.services.store.transaction(write)
        url = authorize_url(client_id=client_id, challenge=verifier.challenge, state=state)
        return AuthStart(authorize_url=url, redirect_uri=REDIRECT_URI, expires_at=expires)

    async def finish_auth(self, redirect_url: str) -> Connection:
        """POST /api/spotify/auth/finish: exchanges the pasted callback's code for tokens."""
        try:
            redirect = parse_redirect(redirect_url)
        except InvalidRedirect as exc:
            raise ApiError(
                422,
                "invalid_redirect",
                "That isn't the callback address. Paste the whole "
                "http://127.0.0.1:8888/callback?... address from the browser.",
            ) from exc
        if redirect.error is not None:
            raise ApiError(422, "access_denied", "You declined on Spotify. Press Authorize again.")
        if redirect.code is None:  # parse_redirect gives a code whenever there's no error
            raise ApiError(422, "invalid_redirect", "The address has no authorization code.")
        pending = await self._claim_pending(redirect.state)

        webapi = self.services.ports.webapi
        try:
            grant = await webapi.exchange_code(
                client_id=pending.client_id,
                code=redirect.code,
                code_verifier=pending.code_verifier,
                redirect_uri=REDIRECT_URI,
                scope=SETUP,
            )
        except TokenExchangeFailed:
            # Only the type is logged: the message and the code stay out of the log.
            log.warning("Web API: Spotify refused the authorization code; press Authorize again")
            raise

        await self.services.auth.save_grant(pending.client_id, grant)
        user = await webapi.me(scope=SETUP)
        await self.services.auth.set_account(user)
        log.info("Web API: authorized")

        # The device check is part of step 5, but a failure here leaves the step for Retry: the
        # connection itself is made.
        try:
            devices = await webapi.devices(scope=SETUP)
        except WebApiError as exc:
            log.warning("Web API: the device check failed (%s)", type(exc).__name__)
        else:
            await self._mark_step_five(devices)

        self.services.catalog.request_refresh("setup")
        return await self.connection()

    async def devices(self) -> Devices:
        """GET /api/spotify/devices: one devices() call. Step 5's Retry."""
        listed = await self.services.ports.webapi.devices(scope=SETUP)
        ours = await self._mark_step_five(listed)
        return Devices(
            devices=[_device_model(device) for device in listed],
            ours=_device_model(ours) if ours is not None else None,
            device_name=self.services.config.device_name,
        )

    async def disconnect(self) -> Connection:
        """DELETE /api/spotify/connection: deletes the token; the Client ID stays."""
        await self._refuse_during_run()
        await self.services.auth.disconnect()
        return await self.connection()

    async def watch(self) -> None:
        """Background task: publishes `connection` when the state crosses `expiring` or
        `expired` with time. Sleeps with services.clock until the next boundary (at most an hour
        at a time), so the FakeClock drives it in tests."""
        clock = self.services.clock
        while True:
            row = await self.services.auth.load()
            boundary = _next_boundary(row, clock.now())
            if boundary is None:
                wait_s = WATCH_MAX_S
            else:
                wait_s = min(WATCH_MAX_S, max(0.0, (boundary - clock.now()).total_seconds()))
            await clock.sleep(wait_s)
            # Woke at a boundary: the state has changed with time, so say so. Anything else
            # (the hour's cap, or a change made while asleep) just loops and reads it again.
            if boundary is not None and clock.now() >= boundary:
                self.services.bus.publish("connection", await self.connection())

    # --- Inside ------------------------------------------------------------------------------

    async def _on_change(self, change: AuthChange) -> None:
        """AuthStore's listener: every connection change is published after it's committed."""
        self.services.bus.publish("connection", await self.connection())

    async def _refuse_during_run(self) -> None:
        """409 `run_active` while a run is recording (setup.py's `_run_is_active`)."""
        row = await self.services.store.fetchone(
            "SELECT 1 FROM runs WHERE kind = 'run' AND state <> 'ended' LIMIT 1"
        )
        if row is not None:
            raise run_active()

    async def _claim_pending(self, state: str | None) -> _Pending:
        """Takes the pending authorization for the pasted `state`, so it's single use.

        Claimed before the exchange: a second paste of the same address finds nothing. A paste
        with another state leaves the pending one alone, so the right address still works.
        """
        now = self.services.clock.now()

        def claim(conn: sqlite3.Connection) -> tuple[str, _Pending | None]:
            row = conn.execute(
                "SELECT state, code_verifier, client_id, expires_at FROM pkce_pending "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return "none", None
            current = conn.execute("SELECT client_id FROM spotify_auth WHERE id = 1").fetchone()
            if (
                now >= _time(row["expires_at"])
                or current is None
                or (current["client_id"] != row["client_id"])
            ):
                # Expired, or the Client ID changed since: drop it.
                conn.execute("DELETE FROM pkce_pending WHERE state = ?", (row["state"],))
                return "none", None
            if state != row["state"]:
                return "state_mismatch", None
            conn.execute("DELETE FROM pkce_pending WHERE state = ?", (row["state"],))
            pending = _Pending(
                state=row["state"],
                code_verifier=row["code_verifier"],
                client_id=row["client_id"],
            )
            return "ok", pending

        outcome, pending = await self.services.store.transaction(claim)
        if outcome == "state_mismatch":
            raise ApiError(
                422,
                "state_mismatch",
                "The address belongs to an older authorization. Press Authorize again.",
            )
        if pending is None:
            raise ApiError(
                422,
                "no_pending_auth",
                "No authorization is in progress, or it expired. Press Authorize again.",
            )
        return pending

    async def _mark_step_five(self, devices: list[Device]) -> Device | None:
        """Step 5's device check: done when our device is listed, failed (with why) when not.
        Returns our device, or None."""
        ours = our_device(devices, self.services.config.device_name)
        if ours is None:
            await self.services.setup.mark_failed("webapi", DEVICE_MISSING)
        else:
            await self.services.setup.mark_done("webapi")
        return ours
