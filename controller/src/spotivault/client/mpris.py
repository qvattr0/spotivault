"""`JeepneyMpris`, the real `ports.Mpris`: the client's MPRIS interface on the session bus.

Built on jeepney's asyncio support, never `dbus-send` (it blocks: design.md § Stack).

- **The bus:** the session bus the image's `dbus` service runs at `$XDG_RUNTIME_DIR/bus`
  (`unix:path=/tmp/runtime-app/bus`, the same as the image's DBUS_SESSION_BUS_ADDRESS).
- **Calls** (properties, player methods, Quit) each open a short connection, make one call and
  close it. That costs a millisecond or two on a local socket, and leaves no connection to go
  stale when the bus restarts.
- **Errors:** property reads return None and `owner_present` False when the client isn't on the
  bus (or the bus is down). Player methods and Quit raise MprisNoClient then: the call can't have
  reached the client. Any other D-Bus error, or no answer within CALL_TIMEOUT_S, raises a plain
  MprisUnavailable, because the client may have got the call: a client quitting can leave the bus
  before it answers (`NoReply`).
- **`subscribe()`** holds one connection with match rules for PropertiesChanged and Seeked on
  /org/mpris/MediaPlayer2, and NameOwnerChanged for config.mpris_name. Entering it raises
  MprisUnavailable when the bus can't be reached; the iterator raises it when the bus closes the
  connection. Closing the connection drops its match rules.
- **Track identity:** `mpris:trackid` is `/com/spotify/track/<id>`, and `TrackMetadata.track_id`
  is that `<id>` (plan D10).
"""

import asyncio
import contextlib
import logging
import re
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from jeepney import (
    AuthenticationError,
    DBusAddress,
    HeaderFields,
    MatchRule,
    Message,
    MessageFlag,
    MessageType,
    Properties,
    message_bus,
    new_method_call,
)
from jeepney.io.asyncio import DBusConnection, open_dbus_connection, open_dbus_router
from jeepney.io.common import RouterClosed
from jeepney.wrappers import DBusErrorResponse, unwrap_msg

from spotivault.clock import SystemClock
from spotivault.config import Config
from spotivault.ports import (
    MprisChange,
    MprisNoClient,
    MprisUnavailable,
    PlaybackStatus,
    TrackMetadata,
)

log = logging.getLogger(__name__)

MPRIS_PATH = "/org/mpris/MediaPlayer2"
ROOT_INTERFACE = "org.mpris.MediaPlayer2"
PLAYER_INTERFACE = "org.mpris.MediaPlayer2.Player"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
BUS_NAME = "org.freedesktop.DBus"
CALL_TIMEOUT_S = 5.0

PLAYBACK_STATUSES: tuple[PlaybackStatus, ...] = ("Playing", "Paused", "Stopped")

# Errors that can come from connecting to the bus or losing it.
_BUS_ERRORS = (OSError, EOFError, TimeoutError, RouterClosed, AuthenticationError)
# The bus's answers when nobody owns the name called: the call never reached the client.
_NO_OWNER_ERRORS = (
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.NameHasNoOwner",
)

# `/com/spotify/track/<id>` (Spotify's MPRIS), or `spotify:track:<id>` (older clients).
_TRACK_ID = re.compile(r"^(?:/com/spotify/track/|spotify:track:)([0-9A-Za-z]{22})$")


def session_bus_address(config: Config) -> str:
    """The session bus: DBUS_SESSION_BUS_ADDRESS, which the image sets to the dbus service's
    `unix:path=$XDG_RUNTIME_DIR/bus`, and which config.py defaults to that."""
    return config.dbus_address


def track_id(trackid: str | None) -> str | None:
    """The 22-character Spotify id in an `mpris:trackid`, or None if it isn't a track's."""
    match = _TRACK_ID.match(trackid or "")
    return match.group(1) if match else None


def parse_metadata(metadata: Mapping[str, Any]) -> TrackMetadata | None:
    """MPRIS `Metadata` (an a{sv}: key → (signature, value)) as TrackMetadata, or None when it's
    empty (nothing loaded)."""
    if not metadata:
        return None

    def value(key: str) -> Any:
        item = metadata.get(key)
        return item[1] if isinstance(item, tuple) and len(item) == 2 else None

    def text(key: str) -> str | None:
        found = value(key)
        return str(found) if isinstance(found, str) and found != "" else None

    trackid = text("mpris:trackid")
    artists = value("xesam:artist")
    length = value("mpris:length")  # microseconds
    return TrackMetadata(
        trackid=trackid,
        track_id=track_id(trackid),
        title=text("xesam:title"),
        artists=tuple(str(a) for a in artists) if isinstance(artists, list) else (),
        album=text("xesam:album"),
        length_ms=length // 1000 if isinstance(length, int) else None,
        url=text("xesam:url"),
        art_url=text("mpris:artUrl"),
    )


class JeepneyMpris:
    """`ports.Mpris` on the session bus, for the client named config.mpris_name."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.bus_address = session_bus_address(config)
        self.name = config.mpris_name
        self.clock = SystemClock()
        self.timeout_s = CALL_TIMEOUT_S
        self._player = DBusAddress(MPRIS_PATH, bus_name=self.name, interface=PLAYER_INTERFACE)
        self._root = DBusAddress(MPRIS_PATH, bus_name=self.name, interface=ROOT_INTERFACE)

    # --- Reading -------------------------------------------------------------------------------

    async def owner_present(self) -> bool:
        try:
            reply = await self._call(message_bus.NameHasOwner(self.name))
        except MprisUnavailable:
            return False
        return bool(reply[0])

    async def playback_status(self) -> PlaybackStatus | None:
        status = await self._get("PlaybackStatus")
        for known in PLAYBACK_STATUSES:
            if status == known:
                return known
        return None

    async def metadata(self) -> TrackMetadata | None:
        metadata = await self._get("Metadata")
        return parse_metadata(metadata) if isinstance(metadata, dict) else None

    async def position_ms(self) -> int | None:
        position = await self._get("Position")  # microseconds
        return position // 1000 if isinstance(position, int) else None

    # --- Player methods ------------------------------------------------------------------------

    async def play(self) -> None:
        await self._call(new_method_call(self._player, "Play"))

    async def pause(self) -> None:
        await self._call(new_method_call(self._player, "Pause"))

    async def play_pause(self) -> None:
        await self._call(new_method_call(self._player, "PlayPause"))

    async def next(self) -> None:
        await self._call(new_method_call(self._player, "Next"))

    async def previous(self) -> None:
        await self._call(new_method_call(self._player, "Previous"))

    async def open_uri(self, uri: str) -> None:
        await self._call(new_method_call(self._player, "OpenUri", "s", (uri,)))

    async def quit(self) -> None:
        await self._call(new_method_call(self._root, "Quit"))

    # --- Changes -------------------------------------------------------------------------------

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[AsyncIterator[MprisChange]]:
        conn = await self._connect()
        changes: AsyncGenerator[MprisChange] | None = None
        try:
            early = await self._add_matches(conn)
            changes = self._changes(conn, early)
            yield changes
        finally:
            if changes is not None:
                with contextlib.suppress(RuntimeError):  # still being iterated elsewhere
                    await changes.aclose()
            with contextlib.suppress(*_BUS_ERRORS):
                await conn.close()

    def match_rules(self) -> list[MatchRule]:
        """The signals `subscribe` asks the bus for."""
        properties = MatchRule(
            type="signal",
            sender=self.name,
            interface=PROPERTIES_INTERFACE,
            member="PropertiesChanged",
            path=MPRIS_PATH,
        )
        properties.add_arg_condition(0, PLAYER_INTERFACE)
        seeked = MatchRule(
            type="signal",
            sender=self.name,
            interface=PLAYER_INTERFACE,
            member="Seeked",
            path=MPRIS_PATH,
        )
        owner = MatchRule(
            type="signal",
            sender=BUS_NAME,
            interface=BUS_NAME,
            member="NameOwnerChanged",
            path="/org/freedesktop/DBus",
        )
        owner.add_arg_condition(0, self.name)
        return [properties, seeked, owner]

    def to_change(self, msg: Message) -> MprisChange | None:
        """One signal as an MprisChange, or None if it isn't one we follow."""
        if msg.header.message_type != MessageType.signal:
            return None
        member = msg.header.fields.get(HeaderFields.member)
        now = self.clock.now()
        if member == "PropertiesChanged":
            interface, changed, _invalidated = msg.body
            if interface != PLAYER_INTERFACE:
                return None
            status = changed.get("PlaybackStatus")
            metadata = changed.get("Metadata")
            playback_status = None
            if status is not None and status[1] in PLAYBACK_STATUSES:
                playback_status = status[1]
            track = parse_metadata(metadata[1]) if metadata is not None else None
            if playback_status is None and track is None:
                return None
            return MprisChange(at=now, playback_status=playback_status, metadata=track)
        if member == "Seeked":
            (position,) = msg.body  # microseconds
            return MprisChange(at=now, seeked_ms=position // 1000)
        if member == "NameOwnerChanged":
            name, _old_owner, new_owner = msg.body
            if name != self.name:
                return None
            return MprisChange(at=now, owner_present=new_owner != "")
        return None

    # --- Inside --------------------------------------------------------------------------------

    async def _get(self, prop: str) -> Any:
        """A Player property's value, or None when the client isn't on the bus."""
        try:
            reply = await self._call(Properties(self._player).get(prop))
        except MprisUnavailable as exc:
            log.debug("mpris: can't read %s: %s", prop, exc)
            return None
        _signature, value = reply[0]
        return value

    async def _call(self, msg: Message) -> tuple[Any, ...]:
        """Makes one method call on its own connection and returns the reply's body.

        Raises MprisNoClient when the call can't have reached the client: the bus can't be
        reached, or the name has no owner. Raises MprisUnavailable for any other error, and when
        the bus is lost or the answer doesn't come once the call was sent.
        """
        msg.header.flags |= MessageFlag.no_auto_start  # never ask the bus to start a service
        sent = False
        try:
            async with asyncio.timeout(self.timeout_s):
                async with open_dbus_router(self.bus_address) as router:
                    sent = True
                    reply = await router.send_and_get_reply(msg)
            return unwrap_msg(reply)
        except DBusErrorResponse as exc:
            text = f"{exc.name}: {_error_text(exc)}"
            if exc.name in _NO_OWNER_ERRORS:
                raise MprisNoClient(text) from exc
            raise MprisUnavailable(text) from exc
        except _BUS_ERRORS as exc:
            if sent:
                raise MprisUnavailable(
                    f"no answer from {self.name} within {self.timeout_s:g} s: {exc!r}"
                ) from exc
            raise MprisNoClient(
                f"the session bus at {self.bus_address} can't be reached: {exc!r}"
            ) from exc

    async def _connect(self) -> DBusConnection:
        try:
            async with asyncio.timeout(self.timeout_s):
                return await open_dbus_connection(self.bus_address)
        except _BUS_ERRORS as exc:
            raise MprisUnavailable(
                f"the session bus at {self.bus_address} can't be reached: {exc!r}"
            ) from exc

    async def _add_matches(self, conn: DBusConnection) -> deque[Message]:
        """Adds the match rules and waits until the bus has taken them all, so no change after
        `subscribe` returns is missed. Signals that arrive meanwhile are returned, in order."""
        waiting: set[int] = set()
        for rule in self.match_rules():
            serial = next(conn.outgoing_serial)
            await conn.send(message_bus.AddMatch(rule), serial=serial)
            waiting.add(serial)
        early: deque[Message] = deque()
        try:
            async with asyncio.timeout(self.timeout_s):
                while waiting:
                    msg = await conn.receive()
                    reply_to = msg.header.fields.get(HeaderFields.reply_serial)
                    if reply_to in waiting:
                        waiting.discard(reply_to)
                        unwrap_msg(msg)  # raises DBusErrorResponse if the bus refused it
                    elif msg.header.message_type == MessageType.signal:
                        early.append(msg)
        except DBusErrorResponse as exc:
            raise MprisUnavailable(f"AddMatch: {exc.name}: {_error_text(exc)}") from exc
        except _BUS_ERRORS as exc:
            raise MprisUnavailable(f"AddMatch: the session bus didn't answer: {exc!r}") from exc
        return early

    async def _changes(
        self, conn: DBusConnection, early: deque[Message]
    ) -> AsyncGenerator[MprisChange]:
        while True:
            if early:
                msg = early.popleft()
            else:
                try:
                    msg = await conn.receive()
                except _BUS_ERRORS as exc:
                    raise MprisUnavailable("the session bus closed the connection") from exc
            change = self.to_change(msg)
            if change is not None:
                yield change


def _error_text(exc: DBusErrorResponse) -> str:
    data = exc.data
    if isinstance(data, tuple) and data and isinstance(data[0], str):
        return data[0]
    return str(data)
