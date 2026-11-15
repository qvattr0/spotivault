"""desktop.py: the real `ports.Desktop` against local sockets standing in for Xvfb, PulseAudio
and x11vnc."""

import asyncio
import contextlib
import socket
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from portcheck import assert_implements
from spotivault import ports
from spotivault.config import Config, load_config
from spotivault.desktop import LocalDesktop, display_number


def test_implements_the_port() -> None:
    assert_implements(LocalDesktop, ports.Desktop)


@pytest.fixture
def short_dir() -> Iterator[Path]:
    """A folder with a short path: a Unix socket's path may be at most 107 bytes."""
    with tempfile.TemporaryDirectory(prefix="sv-") as name:
        yield Path(name)


@contextlib.asynccontextmanager
async def unix_server(path: Path) -> AsyncIterator[None]:
    async def hang_up(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()

    server = await asyncio.start_unix_server(hang_up, path)
    try:
        yield
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize(
    ("display", "number"),
    [(":99", "99"), (":99.0", "99"), ("unix:7", "7"), ("localhost:10.0", None), ("", None)],
)
def test_display_number(display: str, number: str | None) -> None:
    assert display_number(display) == number


def desktop_for(env: dict[str, str], **extra: str) -> LocalDesktop:
    return LocalDesktop(load_config({**env, "SPOTIVAULT_FAKE": "0", **extra}))


async def test_display(env: dict[str, str], short_dir: Path) -> None:
    desktop = desktop_for(env, DISPLAY=":99")
    desktop.x11_socket_dir = short_dir
    assert not await desktop.display_ok()
    async with unix_server(short_dir / "X99"):
        assert await desktop.display_ok()
    assert not await desktop_for(env, DISPLAY="otherhost:0").display_ok()


async def test_audio(env: dict[str, str], short_dir: Path) -> None:
    native = short_dir / "native"
    desktop = desktop_for(env, PULSE_SERVER=f"unix:{native}")
    assert not await desktop.audio_ok()
    async with unix_server(native):
        assert await desktop.audio_ok()
    assert not await desktop_for(env, PULSE_SERVER="tcp:127.0.0.1:4713").audio_ok()


def free_port() -> int:
    """A local port with nothing listening on it (bound, then let go)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_open_vnc(env: dict[str, str]) -> None:
    async def greet(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"RFB 003.008\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(greet, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        desktop = desktop_for(env, SPOTIVAULT_VNC=f"127.0.0.1:{port}")
        reader, writer = await desktop.open_vnc()
        assert await reader.readline() == b"RFB 003.008\n"
        writer.close()
        await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()


async def test_open_vnc_raises_oserror_when_nothing_listens(env: dict[str, str]) -> None:
    desktop = desktop_for(env, SPOTIVAULT_VNC=f"127.0.0.1:{free_port()}")
    with pytest.raises(OSError):
        await desktop.open_vnc()


def test_the_constructor_does_no_io(config: Config) -> None:
    desktop = LocalDesktop(config)
    assert desktop.config is config
