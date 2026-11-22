"""GET /api/health: Docker's healthcheck (openapi.yaml `getHealth`).

The image's HEALTHCHECK curls it every 30 s with a 5 s timeout, after a 60 s start period.
- **503** (`internal`) when the database can't be opened: the container turns unhealthy.
- **200** otherwise, even before setup is done, with `status`:
  - `ok`: the screen (Xvfb) and the sound server (PulseAudio) answer;
  - `starting`: one of them doesn't answer yet, in the controller's first STARTING_S seconds
    (s6 starts them alongside the controller);
  - `degraded`: one of them doesn't answer after that. The container stays healthy, so the UI
    can still be reached to show what's wrong.
- **`checks.client`:** `installing` while a client install runs (the latest `client_install`
  row), else `running`, `stopped` (installed) or `not_installed`.

The checks run at once, each limited to CHECK_TIMEOUT_S, so the answer always beats Docker's 5 s.
A status change is logged once, not on every check.
"""

import asyncio
import logging
from collections.abc import Awaitable
from typing import Literal

from fastapi import APIRouter, Request, Response

from spotivault.api.deps import ServicesDep
from spotivault.api.models import Health, HealthChecks
from spotivault.errors import ApiError
from spotivault.services import Services

log = logging.getLogger(__name__)

router = APIRouter(tags=["system"])

STARTING_S = 60.0  # the HEALTHCHECK's --start-period
CHECK_TIMEOUT_S = 2.0  # each check; they run at once, inside Docker's 5 s timeout
NO_STORE = {"Cache-Control": "no-store"}

type ClientCheck = Literal["not_installed", "installing", "stopped", "running"]
type HealthStatus = Literal["ok", "starting", "degraded"]


@router.get(
    "/api/health",
    operation_id="getHealth",
    response_model=Health,
    responses={503: {"description": "The database can't be opened (`internal`)."}},
)
async def get_health(services: ServicesDep, request: Request, response: Response) -> Health:
    response.headers.update(NO_STORE)
    if not await services.store.ping():
        _note_status(request, "unavailable", f"no database: {services.store.error}")
        raise ApiError(
            503,
            "internal",
            "The database can't be opened.",
            {"db": services.store.error},
            headers=NO_STORE,
        )
    display, audio, client = await asyncio.gather(
        _check("display", services.ports.desktop.display_ok()),
        _check("pulseaudio", services.ports.desktop.audio_ok()),
        _client_state(services),
    )
    uptime_s = max(0, int(services.clock.monotonic() - services.started_monotonic))
    status: HealthStatus
    if display and audio:
        status = "ok"
    elif uptime_s < STARTING_S:
        status = "starting"
    else:
        status = "degraded"
    failing = [name for name, ok in (("display", display), ("pulseaudio", audio)) if not ok]
    _note_status(request, status, f"{', '.join(failing)} not answering" if failing else "")
    return Health(
        status=status,
        version=services.bus.version,
        boot_id=services.bus.boot_id,
        uptime_s=uptime_s,
        checks=HealthChecks(
            db="ok",
            display="ok" if display else "fail",
            pulseaudio="ok" if audio else "fail",
            client=client,
        ),
    )


async def _check(name: str, probe: Awaitable[bool]) -> bool:
    """A check's answer; False when it fails, raises or takes longer than CHECK_TIMEOUT_S."""
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            return await probe
    except TimeoutError:
        log.debug("health: the %s check took over %.0f s", name, CHECK_TIMEOUT_S)
        return False
    except Exception:
        log.exception("health: the %s check failed", name)
        return False


async def _client_state(services: Services) -> ClientCheck:
    client = services.ports.client
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            if await _install_running(services):
                return "installing"
            if await client.is_running():
                return "running"
            return "stopped" if await client.installed_version() else "not_installed"
    except TimeoutError:
        log.debug("health: the client check took over %.0f s", CHECK_TIMEOUT_S)
        return "stopped"
    except Exception:
        log.exception("health: the client check failed")
        return "stopped"


async def _install_running(services: Services) -> bool:
    """True when the latest install attempt in `client_install` (contracts/schema.sql) is still
    running. The client manager marks an attempt cut short by a restart as failed."""
    state = await services.store.fetchval(
        "SELECT state FROM client_install ORDER BY id DESC LIMIT 1"
    )
    return state == "installing"


def _note_status(request: Request, status: str, detail: str) -> None:
    """Logs the health status when it changes. The last one is kept on the app's state."""
    state = request.app.state
    previous = getattr(state, "health_status", None)
    if status == previous:
        return
    state.health_status = status
    if status in ("ok", "starting"):
        log.info("health: %s%s", status, f" ({detail})" if detail else "")
    else:
        log.warning("health: %s (%s)", status, detail)
