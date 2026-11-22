"""fake/world.py, fake/__init__.py, fake/system.py and fake/vnc.py: the scenarios, and the
fake desktop with its VNC screen."""

import asyncio
import struct
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from fake_helpers import make_world
from portcheck import assert_implements
from spotivault import ports
from spotivault.app import create_app
from spotivault.clock import SystemClock
from spotivault.config import Config
from spotivault.fake import FakeWorld, build_fake_ports, world_of
from spotivault.fake.clock import FakeClock
from spotivault.fake.system import FakeDesktop, FakeStorageProbe
from spotivault.fake.vnc import HEIGHT, WIDTH
from spotivault.services import Services, build_services


def test_the_system_ports_implement_their_protocols() -> None:
    assert_implements(FakeStorageProbe, ports.StorageProbe)
    assert_implements(FakeDesktop, ports.Desktop)


def test_tests_start_fresh_and_the_dev_server_starts_set_up(config: Config) -> None:
    fresh = world_of(build_fake_ports(config, FakeClock()))
    assert fresh.scenario == "fresh"
    demo = world_of(build_fake_ports(config, SystemClock()))
    assert demo.scenario == "demo"
    wizard = world_of(build_fake_ports(config, FakeClock(), scenario="wizard"))
    assert wizard.client.auto_login_after_s == 20.0
    with pytest.raises(ValueError, match="unknown fake scenario"):
        FakeWorld(config, FakeClock(), scenario="nope")  # type: ignore[arg-type]


def test_world_of_refuses_real_ports(config: Config) -> None:
    from spotivault.services import build_real_ports

    with pytest.raises(TypeError):
        world_of(build_real_ports(config, SystemClock()))


async def test_a_fresh_world(config: Config, fake_clock: FakeClock) -> None:
    world = make_world(config, fake_clock, scenario="fresh")
    assert await world.client.installed_version() is None
    assert not await world.client.is_running()
    assert not await world.mpris.owner_present()
    with pytest.raises(ports.NotConnected):
        await world.webapi.devices()
    with pytest.raises(ConnectionRefusedError):
        await world.desktop.open_vnc()


async def test_a_demo_world(config: Config, fake_clock: FakeClock) -> None:
    world = make_world(config, fake_clock, scenario="demo", library="fixtures")
    assert await world.client.installed_version() == "1.3.4.258"
    assert await world.client.is_running()
    signals = await world.client.login_signals()
    assert signals.user_folder and signals.window_title == "Spotify Premium"
    devices = await world.webapi.devices()
    assert devices[0].name == config.device_name and len(devices) == 4
    assert (await world.webapi.my_playlists()).total == 18
    assert await world.storage.mount_source(config.music_dir) == "/Music"  # as on the NAS


@pytest.fixture
def demo_services(config: Config, fake_clock: FakeClock) -> Services:
    services = build_services(config, clock=fake_clock)
    services.ports = build_fake_ports(config, fake_clock, scenario="demo")
    return services


@pytest.fixture
async def demo_client(demo_services: Services) -> AsyncIterator[httpx.AsyncClient]:
    app: FastAPI = create_app(demo_services)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
            yield http


async def test_the_demo_health_shows_a_running_client(demo_client: httpx.AsyncClient) -> None:
    body = (await demo_client.get("/api/health")).json()
    assert body["status"] == "ok"
    assert body["checks"]["client"] == "running"


async def vnc_handshake(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> tuple[int, int]:
    """RFB 3.8 as noVNC does it, up to ServerInit. Returns the screen size."""
    assert await reader.readexactly(12) == b"RFB 003.008\n"
    writer.write(b"RFB 003.008\n")
    assert await reader.readexactly(2) == bytes([1, 1])  # one security type: None
    writer.write(bytes([1]))
    assert struct.unpack(">I", await reader.readexactly(4)) == (0,)
    writer.write(bytes([1]))  # ClientInit, shared
    width, height = struct.unpack(">HH", await reader.readexactly(4))
    await reader.readexactly(16)  # the pixel format
    (length,) = struct.unpack(">I", await reader.readexactly(4))
    assert await reader.readexactly(length) == b"spotivault fake screen"
    return width, height


async def read_update(reader: asyncio.StreamReader) -> bytes:
    kind, rects = struct.unpack(">BxH", await reader.readexactly(4))
    assert (kind, rects) == (0, 1)
    x, y, w, h, encoding = struct.unpack(">HHHHi", await reader.readexactly(12))
    assert (x, y, w, h, encoding) == (0, 0, WIDTH, HEIGHT, 0)
    return await reader.readexactly(w * h * 4)


async def test_the_fake_vnc_screen(config: Config, fake_clock: FakeClock) -> None:
    world = make_world(config, fake_clock, scenario="demo")
    reader, writer = await world.desktop.open_vnc()
    try:
        assert await vnc_handshake(reader, writer) == (WIDTH, HEIGHT)
        # noVNC's pixel format: red in the low byte.
        fmt = struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 0, 8, 16)
        writer.write(bytes([0, 0, 0, 0]) + fmt)
        writer.write(struct.pack(">BxH", 2, 1) + struct.pack(">i", 0))  # SetEncodings: raw
        writer.write(struct.pack(">BBHHHH", 3, 0, 0, 0, WIDTH, HEIGHT))  # a full update
        frame = await read_update(reader)
        assert frame[:4] == bytes([0, 0, 0, 0])  # the sidebar is black
        assert frame[(400 * WIDTH + 600) * 4 : (400 * WIDTH + 600) * 4 + 3] == bytes([18] * 3)
    finally:
        writer.close()
        await world.desktop.aclose()
    assert world.desktop.connections == 1


async def test_a_click_on_the_login_screen_logs_the_client_in(
    config: Config, fake_clock: FakeClock
) -> None:
    world = make_world(config, fake_clock, scenario="demo")
    world.client.log_out()
    reader, writer = await world.desktop.open_vnc()
    try:
        await vnc_handshake(reader, writer)
        writer.write(struct.pack(">BBHHHH", 3, 0, 0, 0, WIDTH, HEIGHT))
        login = await read_update(reader)
        assert login != bytes(len(login))
        writer.write(struct.pack(">BBHH", 5, 1, 640, 400))  # a left click
        writer.write(struct.pack(">BBHH", 5, 0, 640, 400))
        for _ in range(20):
            await asyncio.sleep(0)
        assert world.player.logged_in
        assert (await world.client.login_signals()).window_title == "Spotify Premium"
    finally:
        writer.close()
        await world.desktop.aclose()


async def test_vnc_off_refuses_connections(config: Config, fake_clock: FakeClock) -> None:
    world = make_world(config, fake_clock, scenario="demo")
    world.desktop.vnc = False
    with pytest.raises(ConnectionRefusedError):
        await world.desktop.open_vnc()


async def test_the_storage_probe_states(config: Config, fake_clock: FakeClock) -> None:
    world = make_world(config, fake_clock)
    healthy = await world.storage.volume(config.music_dir)
    assert healthy.writable and healthy.mounted
    world.storage.set_state(config.music_dir, mounted=False, free_bytes=1_000)
    sick = await world.storage.volume(config.music_dir)
    assert not sick.mounted and sick.free_bytes == 1_000
