"""The simulated volumes and desktop: `ports.StorageProbe` and `ports.Desktop`.

A test or the fake world changes the fields to reach every state of wizard step 6 (not mounted,
not writable, low on space) and of the health checks (no display, no sound). The desktop serves
the fake VNC screen (`vnc.py`) when it has one, so `WS /vnc` works in fake mode.

Owner: the fake agent.
"""

import asyncio
import logging
import socket
from pathlib import Path

from spotivault.fake.vnc import FakeScreen, serve
from spotivault.ports import VolumeInfo

log = logging.getLogger(__name__)

GB = 1_000_000_000


class FakeStorageProbe:
    """`ports.StorageProbe` with volumes set by hand. Unknown paths look like healthy mounts."""

    def __init__(self) -> None:
        self.volumes: dict[Path, VolumeInfo] = {}
        self.sources: dict[Path, str] = {}  # mount sources, for Settings › Container
        self.world: object | None = None  # the FakeWorld it belongs to

    def set_volume(self, info: VolumeInfo) -> None:
        self.volumes[info.path] = info

    def set_state(
        self,
        path: Path,
        *,
        exists: bool = True,
        mounted: bool = True,
        writable: bool = True,
        free_bytes: int | None = 500 * GB,
        total_bytes: int | None = 1000 * GB,
    ) -> None:
        """One volume's state, field by field: `set_state(music, writable=False)`."""
        self.set_volume(
            VolumeInfo(
                path=path,
                exists=exists,
                mounted=mounted,
                writable=writable,
                free_bytes=free_bytes,
                total_bytes=total_bytes,
            )
        )

    async def volume(self, path: Path) -> VolumeInfo:
        return self.volumes.get(path) or VolumeInfo(
            path=path,
            exists=True,
            mounted=True,
            writable=True,
            free_bytes=500 * GB,
            total_bytes=1000 * GB,
        )

    async def mount_source(self, path: Path) -> str | None:
        return self.sources.get(path)


class FakeDesktop:
    """`ports.Desktop` for fake mode: the screen and sound are fine, and the VNC server is the
    fake one when a screen is given (`vnc = False` refuses connections, like x11vnc down)."""

    def __init__(self, screen: FakeScreen | None = None) -> None:
        self.display = True
        self.audio = True
        self.screen = screen
        self.vnc = screen is not None
        self.connections = 0  # VNC connections opened
        self.world: object | None = None  # the FakeWorld it belongs to
        self._servers: set[asyncio.Task[None]] = set()

    async def display_ok(self) -> bool:
        return self.display

    async def audio_ok(self) -> bool:
        return self.audio

    async def open_vnc(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if not self.vnc or self.screen is None:
            raise ConnectionRefusedError("the fake VNC server is off")
        ours, theirs = socket.socketpair()
        server_reader, server_writer = await asyncio.open_connection(sock=ours)
        task = asyncio.create_task(serve(server_reader, server_writer, self.screen))
        self._servers.add(task)
        task.add_done_callback(self._server_done)
        self.connections += 1
        return await asyncio.open_connection(sock=theirs)

    async def aclose(self) -> None:
        """Ends every VNC connection still open (tests, at the end)."""
        for task in list(self._servers):
            task.cancel()
        if self._servers:
            await asyncio.gather(*self._servers, return_exceptions=True)

    def _server_done(self, task: asyncio.Task[None]) -> None:
        self._servers.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("the fake VNC server failed", exc_info=task.exception())
