"""Read-only container facts for Settings › Container (GET /api/container).

The environment the UGOS Docker app sets (DEVICE_NAME, TZ, UMASK, whether UI_PASSWORD is set),
the host side of the /music mount, and the versions: the image, the controller, Spytify and the
client. Never UI_PASSWORD's value.

Plan D11: M1 doesn't enforce UI_PASSWORD. When it's set, the controller logs a warning at
start-up, and the API reports it (`ui_password_env_set`) so Settings can show the warning too.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from spotivault import __version__
from spotivault.api.models import Container, ContainerVersions

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

UNKNOWN = "unknown"  # versions.spytify when it can't be read; the contract wants a string
VERSION_TIMEOUT_S = 5.0

_VERSION = re.compile(r"\bv?(\d+\.\d+\.\d+[0-9A-Za-z.+-]*)")


def parse_spytifyd_version(output: str) -> str | None:
    """'spytifyd v2.0.2 (linux/amd64)' → '2.0.2'. None when there's no version in it."""
    match = _VERSION.search(output)
    return match.group(1) if match else None


async def spytifyd_version(path: Path, *, timeout_s: float = VERSION_TIMEOUT_S) -> str | None:
    """Runs `spytifyd --version` without blocking the loop. None when it can't be run.

    The real recorder (S6) can answer `ports.Recorder.version()` with this.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            str(path),
            "--version",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        log.warning("container: can't run %s --version: %s", path, exc)
        return None
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout_s)
    except TimeoutError:
        process.kill()
        await process.wait()
        log.warning("container: %s --version didn't answer within %.0f s", path, timeout_s)
        return None
    text = output.decode("utf-8", errors="replace")
    version = parse_spytifyd_version(text) if process.returncode == 0 else None
    if version is None:
        log.warning(
            "container: %s --version exited %s: %r", path, process.returncode, text.strip()[:200]
        )
    return version


class ContainerService:
    """Container facts. Built by services.py as `services.container`."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self._spytify: str | None = None  # the binary is in the image, so it never changes
        services.add_startup("container", self.start)

    async def start(self) -> None:
        if self.services.config.ui_password_set:
            log.warning(
                "UI_PASSWORD is set, but this version doesn't enforce it: the web UI has no "
                "password. Keep spotivault on your LAN."
            )

    async def info(self) -> Container:
        """Settings › Container: environment values and versions. A fact that can't be read is
        null (or "unknown" for Spytify), never an error."""
        config = self.services.config
        ports = self.services.ports
        return Container(
            device_name=config.device_name,
            tz=config.tz,
            music_source=await _safely(
                "the /music mount", lambda: ports.storage.mount_source(config.music_dir)
            ),
            umask=config.umask,
            ui_password_env_set=config.ui_password_set,
            versions=ContainerVersions(
                image=config.image_version,
                controller=__version__,
                spytify=await self.spytify_version() or UNKNOWN,
                client=await _safely("the client's version", ports.client.installed_version),
            ),
        )

    async def spytify_version(self) -> str | None:
        """Spytify's version from the recorder port. Until S6 builds the real recorder, real mode
        asks `spytifyd --version` itself."""
        if self._spytify is None:
            version = await _safely("Spytify's version", self.services.ports.recorder.version)
            if version is None and not self.services.config.fake:
                version = await spytifyd_version(self.services.config.spytifyd_path)
            self._spytify = version
        return self._spytify


async def _safely(what: str, read: Callable[[], Awaitable[str | None]]) -> str | None:
    try:
        return await read()
    except Exception as exc:
        log.warning("container: can't read %s: %s", what, exc)
        return None
