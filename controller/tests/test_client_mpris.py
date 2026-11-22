"""client/mpris.py: `JeepneyMpris` against a private dbus-daemon, with a stand-in MPRIS player on
it. The bus tests are skipped when dbus-daemon isn't installed. They never touch the session bus
of the machine running them, nor the containers'."""

import asyncio
import contextlib
import dataclasses
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from jeepney import (
    DBusAddress,
    HeaderFields,
    Message,
    MessageType,
    message_bus,
    new_error,
    new_method_return,
    new_signal,
)
from jeepney.io.asyncio import DBusConnection, open_dbus_connection

from portcheck import assert_implements
from spotivault import ports
from spotivault.client.mpris import (
    MPRIS_PATH,
    PLAYER_INTERFACE,
    PROPERTIES_INTERFACE,
    ROOT_INTERFACE,
    JeepneyMpris,
    parse_metadata,
    session_bus_address,
    track_id,
)
from spotivault.config import Config
from spotivault.ports import MprisChange, MprisNoClient, MprisUnavailable, TrackMetadata

NAME = "org.mpris.MediaPlayer2.spotify"
TRACK_ID = "4uLU6hMCjMI75M1A2tKUQC"
METADATA: dict[str, tuple[str, Any]] = {
    "mpris:trackid": ("o", f"/com/spotify/track/{TRACK_ID}"),
    "mpris:length": ("t", 213_573_000),
    "mpris:artUrl": ("s", "https://i.scdn.co/image/ab67616d0000b273"),
    "xesam:album": ("s", "Whenever You Need Somebody"),
    "xesam:artist": ("as", ["Rick Astley"]),
    "xesam:title": ("s", "Never Gonna Give You Up"),
    "xesam:url": ("s", f"https://open.spotify.com/track/{TRACK_ID}"),
}
TRACK = TrackMetadata(
    trackid=f"/com/spotify/track/{TRACK_ID}",
    track_id=TRACK_ID,
    title="Never Gonna Give You Up",
    artists=("Rick Astley",),
    album="Whenever You Need Somebody",
    length_ms=213_573,
    url=f"https://open.spotify.com/track/{TRACK_ID}",
    art_url="https://i.scdn.co/image/ab67616d0000b273",
)
WAIT_S = 3.0


# --- Without a bus -----------------------------------------------------------------------------


def test_it_implements_the_port() -> None:
    assert_implements(JeepneyMpris, ports.Mpris)


def test_the_bus_is_in_the_runtime_folder(config: Config) -> None:
    assert session_bus_address(config) == f"unix:path={config.runtime_dir}/bus"
    assert JeepneyMpris(config).name == "org.mpris.MediaPlayer2.spotify"
    other = dataclasses.replace(config, dbus_address="unix:path=/run/user/1000/bus")
    assert session_bus_address(other) == "unix:path=/run/user/1000/bus"


@pytest.mark.parametrize(
    ("trackid", "expected"),
    [
        (f"/com/spotify/track/{TRACK_ID}", TRACK_ID),
        (f"spotify:track:{TRACK_ID}", TRACK_ID),
        (f"/com/spotify/episode/{TRACK_ID}", None),
        ("/com/spotify/track/tooshort", None),
        ("/org/mpris/MediaPlayer2/TrackList/NoTrack", None),
        (None, None),
    ],
)
def test_track_id(trackid: str | None, expected: str | None) -> None:
    assert track_id(trackid) == expected


def test_parse_metadata() -> None:
    assert parse_metadata(METADATA) == TRACK
    assert parse_metadata({}) is None
    partial = parse_metadata({"xesam:title": ("s", "Only a title"), "xesam:artist": ("s", "x")})
    assert partial == TrackMetadata(
        trackid=None,
        track_id=None,
        title="Only a title",
        artists=(),
        album=None,
        length_ms=None,
        url=None,
        art_url=None,
    )


async def test_no_bus_means_no_client(config: Config, tmp_path: Path) -> None:
    nowhere = f"unix:path={tmp_path / 'nothing-here' / 'bus'}"
    mpris = JeepneyMpris(dataclasses.replace(config, dbus_address=nowhere))
    assert await mpris.owner_present() is False
    assert await mpris.playback_status() is None
    assert await mpris.metadata() is None
    assert await mpris.position_ms() is None
    with pytest.raises(MprisNoClient):
        await mpris.play()
    with pytest.raises(MprisUnavailable):
        async with mpris.subscribe():
            pass


# --- A private bus and a stand-in player -------------------------------------------------------


@dataclasses.dataclass
class PrivateBus:
    folder: Path  # the socket is folder/bus
    proc: subprocess.Popen[str]


@pytest.fixture
def private_bus() -> Iterator[PrivateBus]:
    """A private dbus-daemon, listening on <a short temporary folder>/bus."""
    daemon = shutil.which("dbus-daemon")
    if daemon is None:
        pytest.skip("dbus-daemon isn't installed")
    folder = Path(tempfile.mkdtemp(prefix="sv-dbus-"))  # short: a socket path has 108 bytes
    proc = subprocess.Popen(
        [
            daemon,
            "--session",
            "--nofork",
            "--nopidfile",
            f"--address=unix:path={folder / 'bus'}",
            "--print-address=1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert proc.stdout is not None
        if not proc.stdout.readline():  # it prints its address once it listens
            pytest.skip("dbus-daemon didn't start")
        yield PrivateBus(folder, proc)
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def bus_dir(private_bus: PrivateBus) -> Path:
    return private_bus.folder


@pytest.fixture
def mpris(config: Config, bus_dir: Path) -> JeepneyMpris:
    mpris = JeepneyMpris(dataclasses.replace(config, dbus_address=f"unix:path={bus_dir / 'bus'}"))
    mpris.timeout_s = WAIT_S
    return mpris


class StandInPlayer:
    """An MPRIS player on the private bus, as the Spotify client publishes it: Get on the Player
    properties, the player methods, Quit, and the PropertiesChanged and Seeked signals."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.status = "Paused"
        self.metadata = dict(METADATA)
        self.position_us = 12_345_678
        # How it takes Quit: "answer" (and leave the bus), "leave" (leave without answering,
        # as a client on its way out may) or "ignore" (no answer, and stay).
        self.on_quit = "answer"
        self.calls: list[str] = []
        self.conn: DBusConnection | None = None
        self._task: asyncio.Task[None] | None = None
        self._named = asyncio.Event()

    async def start(self) -> None:
        self.conn = await open_dbus_connection(self.address)
        serial = next(self.conn.outgoing_serial)
        await self.conn.send(message_bus.RequestName(NAME), serial=serial)
        self._task = asyncio.create_task(self._serve(serial))
        await asyncio.wait_for(self._named.wait(), WAIT_S)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.wait({self._task})
        if self.conn is not None:
            with contextlib.suppress(OSError):
                await self.conn.close()

    async def emit_changed(self, changed: dict[str, tuple[str, Any]], interface: str) -> None:
        emitter = DBusAddress(MPRIS_PATH, interface=PROPERTIES_INTERFACE)
        await self._send(
            new_signal(emitter, "PropertiesChanged", "sa{sv}as", (interface, changed, []))
        )

    async def emit_seeked(self, position_us: int) -> None:
        emitter = DBusAddress(MPRIS_PATH, interface=PLAYER_INTERFACE)
        await self._send(new_signal(emitter, "Seeked", "x", (position_us,)))

    async def _send(self, msg: Message) -> None:
        assert self.conn is not None
        await self.conn.send(msg)

    async def _serve(self, name_request: int) -> None:
        assert self.conn is not None
        while True:
            msg = await self.conn.receive()
            if msg.header.fields.get(HeaderFields.reply_serial) == name_request:
                self._named.set()
            elif msg.header.message_type == MessageType.method_call:
                await self._answer(msg)
                if self.calls[-1:] == ["Quit"] and self.on_quit == "leave":
                    await self.conn.close()
                    return

    async def _answer(self, msg: Message) -> None:
        interface = msg.header.fields.get(HeaderFields.interface)
        member = msg.header.fields.get(HeaderFields.member)
        if interface == PROPERTIES_INTERFACE and member == "Get":
            _iface, prop = msg.body
            values = {
                "PlaybackStatus": ("s", self.status),
                "Metadata": ("a{sv}", self.metadata),
                "Position": ("x", self.position_us),
            }
            if prop in values:
                await self._send(new_method_return(msg, "v", (values[prop],)))
            else:
                error = "org.freedesktop.DBus.Error.InvalidArgs"
                await self._send(new_error(msg, error, "s", (f"no property {prop}",)))
        elif interface == PLAYER_INTERFACE:
            self.calls.append(" ".join([member, *map(str, msg.body)]))
            await self._send(new_method_return(msg))
        elif interface == ROOT_INTERFACE and member == "Quit":
            self.calls.append("Quit")
            if self.on_quit != "answer":
                return
            await self._send(new_method_return(msg))
            await self._send(message_bus.ReleaseName(NAME))  # the client leaves the bus
        else:
            error = "org.freedesktop.DBus.Error.UnknownMethod"
            await self._send(new_error(msg, error, "s", (f"no {interface}.{member}",)))


@pytest.fixture
async def player(bus_dir: Path) -> AsyncIterator[StandInPlayer]:
    player = StandInPlayer(f"unix:path={bus_dir / 'bus'}")
    await player.start()
    yield player
    await player.stop()


async def test_without_the_client_on_the_bus(mpris: JeepneyMpris) -> None:
    assert await mpris.owner_present() is False
    assert await mpris.playback_status() is None
    assert await mpris.metadata() is None
    with pytest.raises(MprisNoClient, match="NameHasNoOwner|ServiceUnknown"):
        await mpris.pause()
    with pytest.raises(MprisNoClient):
        await mpris.quit()


async def test_reads_the_player(mpris: JeepneyMpris, player: StandInPlayer) -> None:
    assert await mpris.owner_present() is True
    assert await mpris.playback_status() == "Paused"
    assert await mpris.metadata() == TRACK
    assert await mpris.position_ms() == 12_345
    player.status = "Buffering"  # not an MPRIS status
    assert await mpris.playback_status() is None


async def test_player_methods_and_quit(mpris: JeepneyMpris, player: StandInPlayer) -> None:
    await mpris.play()
    await mpris.pause()
    await mpris.play_pause()
    await mpris.next()
    await mpris.previous()
    await mpris.open_uri("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")
    await mpris.quit()
    assert player.calls == [
        "Play",
        "Pause",
        "PlayPause",
        "Next",
        "Previous",
        "OpenUri spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        "Quit",
    ]
    assert await mpris.owner_present() is False  # it left the bus


async def test_a_quit_without_an_answer_may_have_reached_the_client(
    mpris: JeepneyMpris, player: StandInPlayer
) -> None:
    # The client leaves the bus before it answers: the bus answers NoReply for it.
    player.on_quit = "leave"
    with pytest.raises(MprisUnavailable, match="NoReply") as left:
        await mpris.quit()
    assert not isinstance(left.value, MprisNoClient)
    assert player.calls == ["Quit"]


async def test_a_quit_that_times_out_may_have_reached_the_client(
    mpris: JeepneyMpris, player: StandInPlayer
) -> None:
    player.on_quit = "ignore"
    mpris.timeout_s = 0.3
    with pytest.raises(MprisUnavailable, match="no answer") as timed_out:
        await mpris.quit()
    assert not isinstance(timed_out.value, MprisNoClient)
    assert player.calls == ["Quit"]


async def next_change(changes: AsyncIterator[MprisChange]) -> MprisChange:
    return await asyncio.wait_for(anext(changes), WAIT_S)


async def test_subscribe_follows_the_player(mpris: JeepneyMpris, player: StandInPlayer) -> None:
    async with mpris.subscribe() as changes:
        # The root interface's properties aren't followed: the bus doesn't even send them.
        await player.emit_changed({"CanQuit": ("b", True)}, ROOT_INTERFACE)
        await player.emit_changed({"PlaybackStatus": ("s", "Playing")}, PLAYER_INTERFACE)
        change = await next_change(changes)
        assert (change.playback_status, change.metadata, change.seeked_ms) == (
            "Playing",
            None,
            None,
        )

        await player.emit_changed(
            {"Metadata": ("a{sv}", METADATA), "PlaybackStatus": ("s", "Paused")},
            PLAYER_INTERFACE,
        )
        change = await next_change(changes)
        assert (change.playback_status, change.metadata) == ("Paused", TRACK)

        await player.emit_changed({"Volume": ("d", 1.0)}, PLAYER_INTERFACE)  # not followed
        await player.emit_seeked(2_500_000)
        change = await next_change(changes)
        assert change.seeked_ms == 2_500

        await mpris.quit()
        change = await next_change(changes)
        assert change.owner_present is False
        assert change.at.tzinfo is not None


async def test_a_subscription_ends_when_the_bus_goes(
    mpris: JeepneyMpris, private_bus: PrivateBus
) -> None:
    async with mpris.subscribe() as changes:
        reader = asyncio.ensure_future(anext(changes))
        await asyncio.sleep(0.05)
        private_bus.proc.terminate()
        with pytest.raises(MprisUnavailable, match="closed the connection"):
            await asyncio.wait_for(reader, WAIT_S)
