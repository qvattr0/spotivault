"""The real `ports.Desktop`: Xvfb, PulseAudio and x11vnc, as the image runs them.

It serves the health check and the WS /vnc bridge. The checks only see whether each server accepts
a connection on its socket, then hang up; they never speak X11 or the PulseAudio protocol.

- **Screen:** DISPLAY `:99` (or `:99.0`) is Xvfb's socket `/tmp/.X11-unix/X99`; it runs with
  `-nolisten tcp`, so only local displays are checked. A remote one counts as not answering.
- **Sound:** PULSE_SERVER `unix:/path` is PulseAudio's native socket. A TCP server counts as not
  answering: the image never uses one.
- **VNC:** x11vnc on SPOTIVAULT_VNC, `127.0.0.1:5900` by default.

Each connection attempt gives up after CONNECT_TIMEOUT_S.
"""

import asyncio
import contextlib
import re
from pathlib import Path

from spotivault.config import Config

CONNECT_TIMEOUT_S = 2.0
X11_SOCKET_DIR = Path("/tmp/.X11-unix")


class LocalDesktop:
    """`ports.Desktop` for the container. The constructor does no I/O."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.x11_socket_dir = X11_SOCKET_DIR  # tests point it at a temporary folder

    async def display_ok(self) -> bool:
        number = display_number(self.config.display)
        if number is None:
            return False
        return await _unix_socket_answers(self.x11_socket_dir / f"X{number}")

    async def audio_ok(self) -> bool:
        server = self.config.pulse_server
        if not server.startswith("unix:"):
            return False
        return await _unix_socket_answers(Path(server.removeprefix("unix:")))

    async def open_vnc(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.wait_for(
            asyncio.open_connection(self.config.vnc_host, self.config.vnc_port), CONNECT_TIMEOUT_S
        )


def display_number(display: str) -> str | None:
    """The display number of a local DISPLAY (`:99`, `:99.0`, `unix:99`), else None."""
    match = re.fullmatch(r"(?:unix)?:(\d+)(?:\.\d+)?", display.strip())
    return match.group(1) if match else None


async def _unix_socket_answers(path: Path) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_unix_connection(path), CONNECT_TIMEOUT_S)
    except OSError:  # missing, refused, or timed out (TimeoutError is an OSError)
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True
