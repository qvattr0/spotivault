"""The simulated Spotify client's player, and the account's Connect playback around it.

SimPlayer plays the Catalog's contexts in clock time: a track ends after its `duration_ms`, the
next playable entry starts, and so on. It follows what the prototype found on the real client
(prototype/FINDINGS.md):
- **The end of a context:** Spotify never reports Stopped. It loads the first track again and
  pauses on it at 0, and its metadata comes a moment before `Paused` (§ End-of-item handling).
- **Next** on that paused first track starts the second one, so a paused player plays again
  (Spytify bug 1). Next on the last track gives the same end: the first track, paused.
- **Unplayable entries,** local files and empty entries are passed over. A play `offset` at one
  silently starts a different, playable one (§ Matching Spytify's index).
- **A restart of the loaded track** (a play at the same entry) sends only `Seeked`, no new
  metadata, which is how Spytify misses it (bug 2; the SimRecorder models that side).
- **MPRIS `mpris:trackid`** names the entry's own id; GET /me/player reports `relinked_id` when
  the entry has one (row 18). Liked Songs is reported by its playlist alias (row 17).
- **OpenUri of a track** plays it in its album, and at its end the same track starts again (§
  "Playing only the missing tracks").
- **Another device** can take playback over: ours pauses and the other becomes active. A play on
  our device takes it back.

Everything that changes is announced to `listeners` as a PlayerEvent, synchronously and in order:
SimMpris turns them into MPRIS changes, and the SimRecorder reacts to them as Spytify does. The
test-facing methods (`load`, `take_over`, `play_elsewhere`, `pause_by_itself`, …) are how tests
and the fake world change things from the outside.

Owner: the fake agent.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from spotivault.fake.catalog import Catalog, Context, DeviceSpec, Entry
from spotivault.fake.clock import Timer, schedule
from spotivault.ports import (
    Clock,
    Device,
    NotFound,
    PlaybackStatus,
    PlayerState,
    RepeatState,
    TrackMetadata,
    WebApiError,
)

type EventKind = Literal["track", "status", "seeked", "bus", "volume"]


@dataclass(frozen=True, slots=True)
class PlayerEvent:
    """One change in the simulated player, with the player's state right after it."""

    kind: EventKind
    at: datetime
    on_bus: bool
    status: PlaybackStatus
    metadata: TrackMetadata | None  # the loaded track
    position_ms: int
    previous_ended: bool = False  # "track": the track before played to its end
    album_end: bool = False  # "track": the context ended; its first track is loaded, paused next
    seeked_from_ms: int | None = None  # "seeked": the position before the seek


@dataclass(slots=True)
class RemotePlayback:
    """Playback on another of the account's devices (a phone that took over, say)."""

    device: DeviceSpec
    context: Context | None
    index: int
    position_ms: int
    is_playing: bool
    since: float  # monotonic time of the last change, for its progress


def metadata_for(entry: Entry) -> TrackMetadata | None:
    """What MPRIS shows for an entry. Spotify's `xesam:artist` holds only the first artist."""
    track = entry.track
    if track is None:
        return None
    kind = "episode" if track.is_episode else "track"
    ident = track.id
    return TrackMetadata(
        trackid=f"/com/spotify/{kind}/{ident}" if ident else None,
        track_id=ident,
        title=track.name,
        artists=track.artists[:1],
        album=track.album_name,
        length_ms=track.duration_ms,
        url=f"https://open.spotify.com/{kind}/{ident}" if ident else None,
        art_url=entry.art_url,
    )


class SimPlayer:
    """The container's Spotify client as a player, plus the account's Connect state."""

    def __init__(self, clock: Clock, catalog: Catalog) -> None:
        self.clock = clock
        self.catalog = catalog
        self.on_bus = False  # the client runs, so its MPRIS name is on the bus
        self.logged_in = False  # a logged-out client shows the login screen and plays nothing
        self.status: PlaybackStatus = "Stopped"  # only before anything was ever loaded
        self.context: Context | None = None
        self.index = 0
        self.shuffle = False
        self.repeat: RepeatState = "off"
        self.autoplay = False  # Settings › Autoplay: the context moves on at its end
        self.volume = 100  # Spytify marks takes below 100 % as "(low volume)"
        self.active_device_id: str | None = None  # Connect: where playback is
        self.remote: RemotePlayback | None = None  # playback on another device
        self.listeners: list[Callable[[PlayerEvent], None]] = []
        self._anchor_ms = 0.0  # position at `_anchor_t`
        self._anchor_t = clock.monotonic()
        self._end_timer: Timer | None = None
        self._repeat_once = False  # OpenUri of a track: it starts again at its end
        self._played: set[int] = set()  # entries played in this context, for shuffle
        self._shuffle_rng = random.Random(0)

    # --- State ---------------------------------------------------------------------------------

    @property
    def entry(self) -> Entry | None:
        """The loaded entry, if any."""
        if self.context is None or not 0 <= self.index < len(self.context.entries):
            return None
        return self.context.entries[self.index]

    def metadata(self) -> TrackMetadata | None:
        entry = self.entry
        return metadata_for(entry) if entry else None

    def position_ms(self) -> int:
        position = self._anchor_ms
        if self.status == "Playing":
            position += (self.clock.monotonic() - self._anchor_t) * 1000
        return int(min(position, self._length_ms()))

    def window_title(self) -> str | None:
        """The client's main window title (Q2): "Spotify" logged out, "Spotify Premium" logged
        in, "Artist - Title" while playing; None when the client isn't running."""
        if not self.on_bus:
            return None
        if not self.logged_in:
            return "Spotify"
        meta = self.metadata()
        if self.status == "Playing" and meta is not None:
            artist = meta.artists[0] if meta.artists else ""
            return f"{artist} - {meta.title}"
        return "Spotify Premium"

    # --- The client process (FakeClientControl) ------------------------------------------------

    def client_started(self) -> None:
        """The client came up: its MPRIS name is on the bus. A context it had stays loaded,
        paused; a fresh client has nothing loaded (Stopped)."""
        if self.on_bus:
            return
        self.on_bus = True
        if self.context is not None and self.status == "Playing":
            self.status = "Paused"
        self._emit("bus")

    def client_gone(self) -> None:
        """The client quit or was killed: the name leaves the bus, and its device goes offline."""
        if not self.on_bus:
            return
        if self.status == "Playing":
            self._anchor_ms = self.position_ms()
            self._anchor_t = self.clock.monotonic()
            self.status = "Paused"
        self._cancel_end()
        self.on_bus = False
        if self.active_device_id == self.catalog.our_device.id:
            self.active_device_id = None
        self._emit("bus")

    def set_logged_in(self, logged_in: bool) -> None:
        if logged_in == self.logged_in:
            return
        self.logged_in = logged_in
        if not logged_in and self.context is not None:
            self._set_status("Paused")
            self.context = None
            self.status = "Stopped"
            self._emit("track")

    # --- Changing the world (tests and the fake world) -----------------------------------------

    def load(
        self, context_uri: str, *, index: int = 0, position_ms: int = 0, play: bool = False
    ) -> None:
        """Loads a context in our client, as if the user picked it there."""
        context = self._context_or_fail(context_uri)
        self._switch_context(context)
        self._make_ours_active()
        self._move_to(index, position_ms)
        self._set_status("Playing" if play else "Paused")

    def seek_to(self, position_ms: int) -> None:
        """The user drags the position slider in our client."""
        self._seek(position_ms)

    def pause_by_itself(self) -> None:
        """Our player pauses with no other device involved: a network stall, say."""
        self._set_status("Paused")

    def take_over(self, device_name: str = "Pixel 9") -> None:
        """Another device takes playback over mid-track (web-ui.md § Warnings during a run): it
        carries on from here, and our player pauses."""
        device = self._other_device(device_name)
        self.remote = RemotePlayback(
            device=device,
            context=self.context,
            index=self.index,
            position_ms=self.position_ms(),
            is_playing=True,
            since=self.clock.monotonic(),
        )
        self.active_device_id = device.id
        self._set_status("Paused")

    def play_elsewhere(self, device_name: str = "Pixel 9", context_uri: str | None = None) -> None:
        """Another device is playing something (D6: a run must not take playback from it)."""
        device = self._other_device(device_name)
        context = self.catalog.context(context_uri) if context_uri else None
        if context is None and self.catalog.liked:
            context = self.catalog.context(self.catalog.liked_uri)
        self.remote = RemotePlayback(device, context, 0, 0, True, self.clock.monotonic())
        self.active_device_id = device.id
        if self.status == "Playing":
            self._set_status("Paused")

    def stop_elsewhere(self) -> None:
        """The other device pauses. It stays the active device, as on Spotify."""
        if self.remote is not None:
            self.remote.position_ms = self._remote_progress()
            self.remote.is_playing = False

    def set_volume(self, percent: int) -> None:
        self.volume = max(0, min(100, percent))
        self._emit("volume")

    # --- MPRIS (SimMpris, and Spytify's own Next) ----------------------------------------------

    def mpris_play(self) -> None:
        if not self._can_play():
            return
        self._make_ours_active()
        self._set_status("Playing")

    def mpris_pause(self) -> None:
        self._set_status("Paused")

    def mpris_next(self) -> None:
        if not self._can_play():
            return
        self._make_ours_active()
        following = self._next_index()
        if following is None:
            self._end_of_context(previous_ended=False)
            return
        self._move_to(following, 0)
        self._set_status("Playing")

    def mpris_previous(self) -> None:
        if not self._can_play():
            return
        before = self._previous_index()
        if self.position_ms() > 3000 or before is None:
            self._seek(0)
            return
        self._move_to(before, 0)
        self._set_status("Playing")

    def mpris_open_uri(self, uri: str) -> None:
        """OpenUri: a context plays from its start (row 9); a track plays in its album and
        starts again at its end. Anything unknown does nothing."""
        if not (self.on_bus and self.logged_in):
            return
        if uri.startswith("spotify:track:"):
            found = self.catalog.track_context(uri)
            if found is None:
                return
            context, index = found
            self._switch_context(context)
            self._make_ours_active()
            self._move_to(index, 0)
            self._repeat_once = True
            self._set_status("Playing")
            return
        context = self.catalog.context(uri)
        if context is None:
            return
        self._switch_context(context)
        self._make_ours_active()
        self._move_to(self._playable_from(0), 0)
        self._set_status("Playing")

    # --- The Web API's player endpoints (FakeWebApi) -------------------------------------------

    def devices(self) -> list[Device]:
        """GET /me/player/devices: ours while the client runs logged in, and the others."""
        ours = self.catalog.our_device
        listed = []
        if self.on_bus and self.logged_in:
            listed.append(self._device(ours, active=self.active_device_id == ours.id))
        for spec in self.catalog.other_devices:
            listed.append(self._device(spec, active=self.active_device_id == spec.id))
        return listed

    def player_state(self) -> PlayerState | None:
        """GET /me/player, or None (204) when no device is active."""
        if self.remote is not None and self.active_device_id == self.remote.device.id:
            remote = self.remote
            entry = None
            if remote.context is not None and 0 <= remote.index < len(remote.context.entries):
                entry = remote.context.entries[remote.index]
            return PlayerState(
                device=self._device(remote.device, active=True),
                is_playing=remote.is_playing,
                context_uri=remote.context.reported_uri if remote.context else None,
                track_id=_reported_id(entry),
                progress_ms=self._remote_progress(),
                shuffle=self.shuffle,
                repeat=self.repeat,
            )
        ours = self.catalog.our_device
        if self.active_device_id != ours.id or not self.on_bus or self.context is None:
            return None
        return PlayerState(
            device=self._device(ours, active=True),
            is_playing=self.status == "Playing",
            context_uri=self.context.reported_uri,
            track_id=_reported_id(self.entry),
            progress_ms=self.position_ms(),
            shuffle=self.shuffle,
            repeat=self.repeat,
        )

    def api_play(
        self, device_id: str, context_uri: str, offset_uri: str | None, position_ms: int
    ) -> None:
        """PUT /me/player/play: the context on that device, from `offset_uri`. On our device it
        takes playback over from any other (Connect)."""
        spec = self._device_for(device_id)
        if context_uri == "spotify:collection:tracks":
            return  # 204, and nothing plays (row 17)
        if context_uri.endswith(":collection:tracks"):
            raise WebApiError("Invalid context uri", status=400)
        context = self._context_or_fail(context_uri)
        index = self._offset_index(context, offset_uri)
        if spec.id != self.catalog.our_device.id:
            if self.status == "Playing":
                self._set_status("Paused")
            self.remote = RemotePlayback(spec, context, index, position_ms, True, self._now())
            self.active_device_id = spec.id
            return
        same = (
            self.context is not None
            and self.context.uri == context.uri
            and index == self.index
            and self.entry is not None
        )
        self._switch_context(context)
        self._make_ours_active()
        if same:
            self._seek(position_ms)
        else:
            self._move_to(index, position_ms)
        self._set_status("Playing")

    def api_pause(self, device_id: str) -> None:
        spec = self._device_for(device_id)
        if spec.id == self.catalog.our_device.id:
            self._set_status("Paused")
        elif self.remote is not None and self.remote.device.id == spec.id:
            self.stop_elsewhere()

    def api_seek(self, position_ms: int, device_id: str) -> None:
        spec = self._device_for(device_id)
        if spec.id == self.catalog.our_device.id:
            self._seek(position_ms)
        elif self.remote is not None and self.remote.device.id == spec.id:
            self.remote.position_ms = position_ms
            self.remote.since = self._now()

    def api_shuffle(self, state: bool, device_id: str) -> None:
        self._device_for(device_id)
        self.shuffle = state

    def api_repeat(self, state: RepeatState, device_id: str) -> None:
        self._device_for(device_id)
        self.repeat = state

    # --- Inside: playing -----------------------------------------------------------------------

    def _now(self) -> float:
        return self.clock.monotonic()

    def _length_ms(self) -> int:
        entry = self.entry
        return entry.track.duration_ms if entry is not None and entry.track is not None else 0

    def _can_play(self) -> bool:
        return self.on_bus and self.logged_in and self.entry is not None

    def _set_status(self, status: PlaybackStatus) -> None:
        if status == self.status:
            return
        if status == "Playing" and not self._can_play():
            return
        if status == "Paused" and self.entry is None:
            return  # nothing loaded: nothing to pause
        self._anchor_ms = self.position_ms()
        self._anchor_t = self._now()
        self.status = status
        self._schedule_end()
        self._emit("status")

    def _seek(self, position_ms: int) -> None:
        if self.entry is None:
            return
        before = self.position_ms()
        self._anchor_ms = float(max(0, min(position_ms, self._length_ms())))
        self._anchor_t = self._now()
        self._schedule_end()
        self._emit("seeked", seeked_from_ms=before)

    def _move_to(
        self,
        index: int,
        position_ms: int,
        *,
        previous_ended: bool = False,
        album_end: bool = False,
    ) -> None:
        """Loads entry `index` at `position_ms`. A different track sends new metadata; the same
        one only a seek (the restart case, bug 2)."""
        if self.context is None:
            return
        if index == self.index and self.entry is not None and not previous_ended:
            self._seek(position_ms)
            return
        self.index = index
        self._played.add(index)
        self._repeat_once = False
        self._anchor_ms = float(max(0, min(position_ms, self._length_ms())))
        self._anchor_t = self._now()
        self._schedule_end()
        self._emit("track", previous_ended=previous_ended, album_end=album_end)

    def _switch_context(self, context: Context) -> None:
        """Makes `context` the loaded one. A different context has no entry loaded yet."""
        if self.context is None or self.context.uri != context.uri:
            self._played = set()
            self.index = -1
        self.context = context

    def _make_ours_active(self) -> None:
        self.active_device_id = self.catalog.our_device.id
        if self.remote is not None:
            self.remote = None

    def _schedule_end(self) -> None:
        self._cancel_end()
        if self.status != "Playing" or self.entry is None:
            return
        remaining_s = max(0.0, (self._length_ms() - self._anchor_ms) / 1000)
        self._end_timer = schedule(self.clock, remaining_s, self._track_ended)

    def _cancel_end(self) -> None:
        if self._end_timer is not None:
            self._end_timer.cancel()
            self._end_timer = None

    def _track_ended(self) -> None:
        """The loaded track played to its end: what Spotify does next."""
        self._end_timer = None
        if self.status != "Playing" or self.context is None:
            return
        self._anchor_ms = float(self._length_ms())
        self._anchor_t = self._now()
        if self.repeat == "track" or self._repeat_once:
            repeat_once = self._repeat_once
            self._move_to(self.index, 0, previous_ended=True)
            self._repeat_once = repeat_once
            return
        following = self._next_index()
        if following is not None:
            self._move_to(following, 0, previous_ended=True)
            return
        if self.repeat == "context":
            self._move_to(self._playable_from(0), 0, previous_ended=True)
            return
        if self.autoplay:
            self._switch_context(self.catalog.radio(self.context))
            self._move_to(self._playable_from(0), 0, previous_ended=True)
            return
        self._end_of_context(previous_ended=True)

    def _end_of_context(self, *, previous_ended: bool) -> None:
        """Spotify loads the first track again and pauses on it; the metadata comes first."""
        first = self._playable_from(0)
        if first == self.index:
            # A one-track context: no new metadata, only the position back to 0.
            before = self.position_ms()
            self._anchor_ms = 0.0
            self._anchor_t = self._now()
            self._schedule_end()
            self._emit(
                "seeked", previous_ended=previous_ended, album_end=True, seeked_from_ms=before
            )
        else:
            self._move_to(first, 0, previous_ended=previous_ended, album_end=True)
        self._set_status("Paused")

    def _playable_from(self, start: int) -> int:
        """The first playable entry at or after `start`, wrapping round; `start` if none is."""
        entries = self.context.entries if self.context else []
        for step in range(len(entries)):
            index = (start + step) % len(entries)
            if entries[index].playable:
                return index
        return start

    def _next_index(self) -> int | None:
        entries = self.context.entries if self.context else []
        if self.shuffle:
            left = [i for i, e in enumerate(entries) if e.playable and i not in self._played]
            return self._shuffle_rng.choice(left) if left else None
        for index in range(self.index + 1, len(entries)):
            if entries[index].playable:
                return index
        return None

    def _previous_index(self) -> int | None:
        entries = self.context.entries if self.context else []
        for index in range(self.index - 1, -1, -1):
            if entries[index].playable:
                return index
        return None

    def _offset_index(self, context: Context, offset_uri: str | None) -> int:
        if offset_uri is None:
            return self._playable_in(context, 0)
        for index, entry in enumerate(context.entries):
            if entry.track is not None and entry.track.uri == offset_uri:
                return self._playable_in(context, index)
        raise WebApiError("Can't play at that offset: it isn't in the context", status=400)

    @staticmethod
    def _playable_in(context: Context, start: int) -> int:
        """An offset at an unplayable entry plays a different, playable one."""
        entries = context.entries
        for step in range(len(entries)):
            index = (start + step) % len(entries)
            if entries[index].playable:
                return index
        raise WebApiError("Player command failed: nothing playable", status=403)

    # --- Inside: devices and lookups -----------------------------------------------------------

    def _context_or_fail(self, uri: str) -> Context:
        context = self.catalog.context(uri)
        if context is None:
            raise NotFound(f"no such context: {uri}", status=404)
        return context

    def _device_for(self, device_id: str) -> DeviceSpec:
        """The device a player call names. Ours counts only while the client runs logged in."""
        ours = self.catalog.our_device
        if device_id == ours.id and self.on_bus and self.logged_in:
            return ours
        for spec in self.catalog.other_devices:
            if spec.id == device_id:
                return spec
        raise NotFound("Device not found", status=404)

    def _other_device(self, name: str) -> DeviceSpec:
        for spec in self.catalog.other_devices:
            if spec.name == name:
                return spec
        raise ValueError(f"no other device named {name!r}")

    def _device(self, spec: DeviceSpec, *, active: bool) -> Device:
        ours = spec.id == self.catalog.our_device.id
        return Device(
            id=spec.id,
            name=spec.name,
            type=spec.type,
            is_active=active,
            is_restricted=False,
            volume_percent=self.volume if ours else spec.volume_percent,
        )

    def _remote_progress(self) -> int:
        remote = self.remote
        if remote is None:
            return 0
        if not remote.is_playing:
            return remote.position_ms
        return remote.position_ms + int((self._now() - remote.since) * 1000)

    def _emit(
        self,
        kind: EventKind,
        *,
        previous_ended: bool = False,
        album_end: bool = False,
        seeked_from_ms: int | None = None,
    ) -> None:
        event = PlayerEvent(
            kind=kind,
            at=self.clock.now(),
            on_bus=self.on_bus,
            status=self.status,
            metadata=self.metadata(),
            position_ms=self.position_ms(),
            previous_ended=previous_ended,
            album_end=album_end,
            seeked_from_ms=seeked_from_ms,
        )
        for listener in list(self.listeners):
            listener(event)


def _reported_id(entry: Entry | None) -> str | None:
    """The track id GET /me/player gives: a relinked one when the entry has it (row 18)."""
    if entry is None or entry.track is None:
        return None
    return entry.relinked_id or entry.track.id
