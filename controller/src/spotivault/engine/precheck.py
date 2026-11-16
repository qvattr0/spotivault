"""The pre-run check, in the run's `starting` state (plan § Run states; web-ui.md § User flows
5, Failure).

Owner: **engine-run**. Called by engine/run.py once a run's row is in.

In order, stopping at the first failure (its RunFailure reason in brackets):
1. Setup complete: `services.setup.is_complete()` [setup_incomplete].
2. The connection: `services.connection.held_reason()` [connection_expired, not_connected].
3. The client installed and, while running, logged in: `services.client.refresh()`
   [recorder when it isn't installed, client_logged_out]. A client that isn't running is left
   to step 4: s6 starts it again, and the device check waits for it.
4. Our device listed: `ports.webapi.devices(scope=ApiScope("run", run_id))` and
   `connection.our_device(devices, config.device_name)`. If it isn't, restart the client once
   (through the client port: the client module refuses a restart during a run), with an
   `error` event (code client_restarted), and wait up to 60 s for it to be listed again
   [device_missing].
5. The Auto checklist rows: `services.client.drifted_rows()` must be empty [setting_drifted].
6. Storage: `services.storage.check()` ok, `/music` writable with at least 2 GB free [storage,
   with an `error` event].
7. The catalog refresh: `services.catalog.refresh(trigger="run", run_id=run_id)`. A refresh that
   fails or is partial doesn't fail the run (items whose lists it couldn't read play whole or
   keep their stored lists); its `snapshots_unread` reach the item jobs (D13). A refresh that
   raises is logged, and the run plays every followed and linked playlist whole.
8. D6: `ports.webapi.player_state()` shows another device playing → `device_busy` (not a
   failure: the run starts paused and never takes playback).

Web API errors in steps 4 and 8: NotConnected and ConnectionExpired fail the run with that
reason (the banner already says why); any other is [webapi], with an `error` event.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from spotivault.connection import our_device
from spotivault.engine.types import ControllerErrorCode, RunFailure
from spotivault.ports import (
    ApiScope,
    ConnectionExpired,
    Device,
    NotConnected,
    WebApiError,
)
from spotivault.storage import storage_problem

if TYPE_CHECKING:
    from spotivault.catalog.refresh import RefreshResult
    from spotivault.services import Services

log = logging.getLogger(__name__)

DEVICE_WAIT_S = 60.0  # after the restart, how long our device may take to be listed again
DEVICE_POLL_S = 5.0  # how often the device list is read meanwhile


@dataclass(frozen=True, slots=True)
class PreRunResult:
    failure: RunFailure | None  # None: the run may go on
    device: Device | None = None  # ours
    device_busy: Device | None = None  # D6: another device is playing
    refresh: "RefreshResult | None" = None
    refresh_failed: bool = False  # the refresh raised: no snapshot_id was read


class _Failed(Exception):
    """Ends the check with this failure."""

    def __init__(self, failure: RunFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


async def pre_run_check(services: "Services", run_id: int) -> PreRunResult:
    """The check above, for run `run_id`. Never raises for a failed check: the result says it."""
    scope = ApiScope("run", run_id)
    try:
        await _setup_and_connection(services)
        await _client(services)
        device = await _our_device_or_restart(services, run_id, scope)
        await _checklist(services)
        await _storage(services, run_id)
    except _Failed as failed:
        log.warning("runs: run %d can't start: %s", run_id, failed.failure.message)
        return PreRunResult(failure=failed.failure)

    refresh: RefreshResult | None = None
    refresh_failed = False
    try:
        refresh = await services.catalog.refresh(trigger="run", run_id=run_id)
    except Exception:
        log.exception(
            "runs: run %d's catalog refresh failed; followed playlists play whole", run_id
        )
        refresh_failed = True

    try:
        busy = await _other_device_playing(services, scope, device)
    except _Failed as failed:
        log.warning("runs: run %d can't start: %s", run_id, failed.failure.message)
        return PreRunResult(failure=failed.failure, refresh=refresh)
    return PreRunResult(
        failure=None,
        device=device,
        device_busy=busy,
        refresh=refresh,
        refresh_failed=refresh_failed,
    )


# --- The steps ---------------------------------------------------------------------------------


async def _setup_and_connection(services: "Services") -> None:
    if not await services.setup.is_complete():
        raise _Failed(RunFailure("setup_incomplete", "Setup isn't complete."))
    held = await services.connection.held_reason()
    if held == "connection_expired":
        raise _Failed(RunFailure("connection_expired", "The Spotify connection expired."))
    if held == "not_connected":
        raise _Failed(RunFailure("not_connected", "The Spotify Web API isn't connected."))


async def _client(services: "Services") -> None:
    status = await services.client.refresh()
    if not status.installed:
        raise _Failed(RunFailure("recorder", "The Spotify client isn't installed."))
    if status.running and not status.logged_in:
        raise _Failed(RunFailure("client_logged_out", "The Spotify client is logged out."))


async def _our_device_or_restart(services: "Services", run_id: int, scope: ApiScope) -> Device:
    """Our Connect device. When it isn't listed, the client is restarted once and the list read
    again every 5 s for up to 60 s."""
    device = await _find_our_device(services, scope)
    if device is not None:
        return device
    name = services.config.device_name
    log.warning("runs: our device %r isn't listed; restarting the Spotify client", name)
    publish_error(
        services,
        "client_restarted",
        f"The device {name} wasn't listed, so the Spotify client was restarted.",
        run_id=run_id,
    )
    try:
        await services.ports.client.restart()
    except Exception:
        log.exception("runs: restarting the Spotify client failed")
    clock = services.clock
    deadline = clock.monotonic() + DEVICE_WAIT_S
    while clock.monotonic() < deadline:
        await clock.sleep(min(DEVICE_POLL_S, max(0.0, deadline - clock.monotonic())))
        try:
            device = await _find_our_device(services, scope)
        except _Failed as failed:
            if failed.failure.reason != "webapi":
                raise
            continue  # Spotify had a hiccup: try again until the 60 s are over
        if device is not None:
            await services.client.refresh()
            return device
    raise _Failed(
        RunFailure("device_missing", f"The device {name} isn't listed, even after a restart.")
    )


async def _find_our_device(services: "Services", scope: ApiScope) -> Device | None:
    try:
        devices = await services.ports.webapi.devices(scope=scope)
    except WebApiError as exc:
        raise _web_api_failure(services, scope, exc, "reading the devices") from exc
    device = our_device(devices, services.config.device_name)
    if device is None or device.id is None:
        return None
    return device


async def _checklist(services: "Services") -> None:
    drifted = await services.client.drifted_rows()
    if drifted:
        rows = ", ".join(row.id for row in drifted)
        raise _Failed(RunFailure("setting_drifted", f"A client setting has changed: {rows}."))


async def _storage(services: "Services", run_id: int) -> None:
    storage = await services.storage.check()
    if storage.ok:
        return
    message = storage_problem(storage) or "The music folder can't be recorded to."
    publish_error(services, "storage", message, run_id=run_id)
    raise _Failed(RunFailure("storage", message))


async def _other_device_playing(
    services: "Services", scope: ApiScope, ours: Device
) -> Device | None:
    """D6: the device that's playing, when it isn't ours."""
    try:
        state = await services.ports.webapi.player_state(scope=scope)
    except WebApiError as exc:
        raise _web_api_failure(services, scope, exc, "reading the player") from exc
    if state is None or not state.is_playing or state.device is None:
        return None
    if state.device.id == ours.id:
        return None
    return state.device


def _web_api_failure(
    services: "Services", scope: ApiScope, exc: WebApiError, doing: str
) -> _Failed:
    if isinstance(exc, ConnectionExpired):
        return _Failed(RunFailure("connection_expired", "The Spotify connection expired."))
    if isinstance(exc, NotConnected):
        return _Failed(RunFailure("not_connected", "The Spotify Web API isn't connected."))
    message = f"The Spotify Web API failed while {doing}: {exc}"
    publish_error(services, "webapi", message, run_id=scope.id)
    return _Failed(RunFailure("webapi", message))


# --- Events ------------------------------------------------------------------------------------


def publish_error(
    services: "Services",
    code: ControllerErrorCode,
    message: str,
    *,
    run_id: int | None,
    item_id: str | None = None,
    fatal: bool = False,
    facts: dict[str, Any] | None = None,
) -> None:
    """An `error` event from the controller (contracts/events.md)."""
    services.bus.publish(
        "error",
        {
            "source": "controller",
            "code": code,
            "message": message,
            "fatal": fatal,
            "withdrawn": False,
            "run_id": run_id,
            "item_id": item_id,
            "facts": facts,
        },
    )
