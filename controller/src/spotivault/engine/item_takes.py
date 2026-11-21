"""The takes of one item attempt: their rows, the relayed `track.*` events, the distinct-track
counts and the live track table (engine/item.py keeps one TakeBook per attempt).

Owner: **engine-item**.

**A take** is one Spytify recording attempt, from `track.started` (its `id` is the take id) to
`track.finished` or `track.skipped`. Each take gets one `track_results` row when it starts
(result NULL while it records), and a `files` row when its file is saved.

**Results** (contracts/schema.sql `track_results.reason`):

| Spytify says | Result |
|---|---|
| `track.finished`, counted | recorded |
| `track.finished`, low_volume | failed `low_volume` |
| `track.finished`, pause_fade | failed `interrupted` |
| `track.finished`, partial | failed `discarded` |
| `track.skipped incomplete`, planned | failed `interrupted` (a stall, takeover, shutdown) |
| `track.skipped`, otherwise | skipped, with Spytify's reason (a cut take not planned stays so) |
| nothing by the end (a kill) | failed `recorder_error` after a file error, else as a cut take |

A planned take Stop now cut (the user's, or the window's end) fails `discarded` instead; once the
context moved on (autoplay), a cut take is the new context's, so it's only skipped `incomplete`.

**Counts are distinct tracks, not events** (FINDINGS: one run counted 10 skips for a 5-track
album). Two kinds of take aren't counted, and don't change the live table:
- **phantom** takes: a track that "started" while the player was paused. That's Spytify forcing
  Spotify's end-of-context change at the idle exit (the paused track 1), never a real play;
- **repeat** takes: a track already counted in this attempt that comes round again (the loop
  guard's case), so a duplicate skip never hides the recording before it.
Each other track counts once, under its result. Their `track_results` rows and `track.*` events
carry no `track_id` or `position`: they aren't a play of that entry, and the Library's and
Albums' "last result" of a track must stay the counted take's (catalog/library.py, albums.py).

**Paths** in rows and events are relative to the music folder (Spytify reports absolute ones).
"""

import logging
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from spotivault.api.models import NowPlaying, RunTrack
from spotivault.clock import iso_ms
from spotivault.engine.planning import ItemPlan, PlannedTrack
from spotivault.engine.types import ItemJob, TrackCounts
from spotivault.recorder import protocol as sp

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

type TakeResult = Literal["recorded", "skipped", "failed"]
# How a planned take cut short fails; None: it isn't a failure (the context moved on).
type CutReason = Literal["interrupted", "discarded"]

_SPOTIFY_ID = re.compile(r"^[0-9A-Za-z]{22}$")
_FILE_ERRORS = frozenset({"read", "encode", "rename"})  # Spytify errors that lose a take's file
# Spytify's skip reasons, as track_results.reason takes them.
_SKIP_REASONS = frozenset(
    {"duplicate", "too_short", "ad", "incomplete", "seeked", "low_quality", "silent"}
)


@dataclass(slots=True)
class Take:
    """One take, as the item engine knows it."""

    take_id: str
    artist: str  # the first artist, as MPRIS gives it
    title: str
    album: str
    length_ms: int
    cover_url: str
    key: str  # Spytify's track key (matching.track_key)
    started_at: datetime
    track: PlannedTrack | None = None  # the item's entry it was matched to (D10)
    mpris_track_id: str | None = None  # the id in mpris:trackid, when MPRIS agreed in time
    planned: bool = False
    phantom: bool = False  # started while the player was paused: never counted
    repeat: bool = False  # this track was already counted in this attempt
    result: TakeResult | None = None
    reason: str | None = None
    path: str | None = None  # relative to the music folder
    bytes: int = 0

    @property
    def track_id(self) -> str | None:
        """The matched entry's id (a `tracks` row): what the rows and events carry."""
        return self.track.track_id if self.track is not None else None

    @property
    def identity(self) -> str:
        """What makes two takes the same track: the item's entry, else Spytify's key."""
        return self.track_id or self.key

    @property
    def counted(self) -> bool:
        return not (self.phantom or self.repeat)

    @property
    def shown_track_id(self) -> str | None:
        """The track id the rows and events carry: none for a take that isn't counted."""
        return self.track_id if self.counted else None

    @property
    def shown_position(self) -> int | None:
        """The entry's 0-based position for the rows and events: none for a take not counted."""
        return self.track.position if self.track is not None and self.counted else None


class TakeBook:
    """Every take of one attempt, in the order they started."""

    def __init__(
        self,
        services: "Services",
        job: ItemJob,
        plan: ItemPlan,
        *,
        file_format: str,
        bitrate: int | None,
    ) -> None:
        self.services = services
        self.job = job
        self.plan = plan
        self.file_format = file_format  # encode.format, for the files rows
        self.bitrate = bitrate
        self.takes: dict[str, Take] = {}  # by take id, in start order
        self.now_playing: NowPlaying | None = None
        self._counted: set[str] = set()  # identities with a counted take
        self._rows: list[RunTrack] = []  # the live track table
        self._row_of: dict[str, int] = {}  # "#<position>", or a take's identity → index in _rows
        if plan.mode == "missing_only":
            missing = {track.position for track in plan.missing}
            for track in plan.tracks:
                self._add_row(
                    _position_key(track.position),
                    RunTrack(
                        position=track.position + 1,
                        track_id=track.track_id,
                        title=track.title,
                        artists=list(track.artists),
                        duration_ms=track.duration_ms,
                        state="pending" if track.position in missing else "recorded",
                        size_bytes=None,
                        reason=None,
                        take_id=None,
                    ),
                )

    # --- What the engine reads -------------------------------------------------------------------

    def get(self, take_id: str) -> Take | None:
        return self.takes.get(take_id)

    def open_take(self) -> Take | None:
        """The take recording now: the newest one without a result that isn't a phantom."""
        for take in reversed(self.takes.values()):
            if take.result is None and not take.phantom:
                return take
        return None

    def counts(self) -> TrackCounts:
        """Distinct tracks under their result (module docstring)."""
        by_track: dict[str, Take] = {}
        for take in self.takes.values():
            if take.counted and take.result is not None:
                by_track[take.identity] = take
        results = list(by_track.values())
        return TrackCounts(
            recorded=sum(1 for t in results if t.result == "recorded"),
            skipped_duplicate=sum(
                1 for t in results if t.result == "skipped" and t.reason == "duplicate"
            ),
            skipped_other=sum(
                1 for t in results if t.result == "skipped" and t.reason != "duplicate"
            ),
            failed=sum(1 for t in results if t.result == "failed"),
            bytes=sum(t.bytes for t in results if t.result == "recorded"),
        )

    def failed_reasons(self) -> Counter[str]:
        """How many counted tracks failed, by reason ("low_volume": 2)."""
        reasons: Counter[str] = Counter()
        for take in self.takes.values():
            if take.counted and take.result == "failed":
                reasons[take.reason or "failed"] += 1
        return reasons

    def rows(self) -> tuple[RunTrack, ...]:
        return tuple(self._rows)

    def done_keys(self) -> frozenset[str]:
        """The Spytify keys this attempt has recorded, for the run's time left: each recorded
        take's, and each planned take's that plays or played and has no result yet (Spytify
        saves a take only after the next one started, or in Finishing), with the key of the
        planned track each one matched (the stored key, should the two differ). Spytify skips
        them from now on."""
        keys: set[str] = set()
        for take in self.takes.values():
            pending = take.result is None and take.planned and not take.phantom
            if take.result != "recorded" and not pending:
                continue
            keys.add(take.key)
            if take.track is not None:
                keys.add(take.track.key)
        return frozenset(keys)

    def heard(self) -> list[Take]:
        """The counted takes that really played, in order: a whole pass's observed tracks."""
        return [take for take in self.takes.values() if take.counted]

    def skipped_for(self, reasons: frozenset[str]) -> list[Take]:
        """The counted takes Spytify skipped for one of `reasons`."""
        return [
            take
            for take in self.takes.values()
            if take.counted and take.result == "skipped" and take.reason in reasons
        ]

    # --- Spytify's events ------------------------------------------------------------------------

    async def start(self, take: Take) -> None:
        """A take began: its row (result NULL), its live row, and the relayed track.started."""
        take.repeat = not take.phantom and take.identity in self._counted
        if take.counted:
            self._counted.add(take.identity)
        self.takes[take.take_id] = take
        position = take.shown_position
        await self.services.store.execute(
            "INSERT INTO track_results (run_item_id, take_id, track_id, position, artist, title, "
            "length_ms, planned, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (run_item_id, take_id) DO NOTHING",
            (
                self.job.run_item_id,
                take.take_id,
                take.shown_track_id,
                position,
                take.artist,
                take.title,
                take.length_ms or None,
                1 if take.planned else 0,
                iso_ms(take.started_at),
            ),
        )
        if take.counted:
            self.now_playing = NowPlaying(
                take_id=take.take_id,
                track_id=take.track_id,
                title=take.title,
                artist=take.artist,
                album=take.album or None,
                cover_url=take.cover_url or None,
                length_ms=max(0, take.length_ms),
                started_at=take.started_at,
                position=position + 1 if position is not None else None,
            )
            self._update_row(take, state="recording")
        self.services.bus.publish(
            "track.started",
            {
                "run_id": self.job.run_id,
                "item_id": self.job.item_id,
                "take_id": take.take_id,
                "artist": take.artist,
                "title": take.title,
                "album": take.album or None,
                "length_ms": take.length_ms,
                "cover_url": take.cover_url or None,
                "track_id": take.shown_track_id,
                "position": position + 1 if position is not None else None,
                "planned": take.planned,
            },
        )

    async def finish(self, event: sp.TrackFinished) -> bool:
        """A take's file was saved. Returns False for a take this book doesn't know."""
        take = self.takes.get(event.id)
        if take is None or take.result is not None:
            if take is None:
                log.warning("track.finished for an unknown take %s: ignored", event.id)
            return False
        if event.counted:
            result: TakeResult = "recorded"
            reason: str | None = None
        elif event.low_volume:
            result, reason = "failed", "low_volume"
        elif event.pause_fade:
            result, reason = "failed", "interrupted"
        else:
            result, reason = "failed", "discarded"  # partial: a held take saved with track.keep
        path = self.relative(event.path)
        now = iso_ms(self.services.clock.now())

        def save(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO files (track_id, spytify_key, path, bytes, duration_ms, format, "
                "bitrate, counted, run_id, take_id, recorded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (run_id, take_id) DO NOTHING",
                (
                    take.track_id,
                    take.key,
                    path,
                    max(0, event.bytes),
                    max(0, event.duration_ms),
                    self.file_format,
                    self.bitrate,
                    1 if event.counted else 0,
                    self.job.run_id,
                    take.take_id,
                    now,
                ),
            )
            file_id = conn.execute(
                "SELECT id FROM files WHERE run_id = ? AND take_id = ?",
                (self.job.run_id, take.take_id),
            ).fetchone()[0]
            conn.execute(
                "UPDATE track_results SET result = ?, reason = ?, file_id = ?, finished_at = ? "
                "WHERE run_item_id = ? AND take_id = ?",
                (result, reason, file_id, now, self.job.run_item_id, take.take_id),
            )

        await self.services.store.transaction(save)
        take.result, take.reason, take.path = result, reason, path
        take.bytes = max(0, event.bytes) if event.counted else 0
        self._take_done(take)
        self.services.bus.publish(
            "track.finished",
            {
                "run_id": self.job.run_id,
                "item_id": self.job.item_id,
                "take_id": take.take_id,
                "track_id": take.shown_track_id,
                "path": path,
                "duration_ms": max(0, event.duration_ms),
                "bytes": max(0, event.bytes),
                "counted": event.counted,
                "low_volume": event.low_volume,
                "pause_fade": event.pause_fade,
                "partial": event.partial,
            },
        )
        return True

    async def skip(self, event: sp.TrackSkipped, *, cut_reason: CutReason | None) -> bool:
        """A take wasn't saved. Returns False for a take this book doesn't know."""
        take = self.takes.get(event.id)
        if take is None or take.result is not None:
            if take is None:
                log.warning("track.skipped for an unknown take %s: ignored", event.id)
            return False
        if event.reason == "incomplete" and take.planned and cut_reason is not None:
            result: TakeResult = "failed"
            reason: str = cut_reason
        elif event.reason in _SKIP_REASONS:
            result, reason = "skipped", event.reason
        else:
            log.warning("take %s skipped for an unknown reason %r", take.take_id, event.reason)
            result, reason = "skipped", "incomplete"
        await self._set_result(take, result, reason)
        path = self.relative(event.path) if event.path else None
        self.services.bus.publish(
            "track.skipped",
            {
                "run_id": self.job.run_id,
                "item_id": self.job.item_id,
                "take_id": take.take_id,
                "reason": event.reason,
                "path": path,
                "track_id": take.shown_track_id,
            },
        )
        return True

    async def close_unfinished(self, *, cut_reason: CutReason | None, file_error: bool) -> bool:
        """Takes that never got a result (the recorder was killed, or a file was lost): failed
        (planned) or skipped `incomplete` (not planned). Returns True when any changed."""
        changed = False
        for take in self.takes.values():
            if take.result is not None:
                continue
            if file_error and not take.phantom:
                await self._set_result(take, "failed", "recorder_error")
            elif take.planned and cut_reason is not None:
                await self._set_result(take, "failed", cut_reason)
            else:
                await self._set_result(take, "skipped", "incomplete")
            changed = True
        return changed

    # --- Helpers -------------------------------------------------------------------------------

    def relative(self, path: str) -> str:
        """A path Spytify reported, relative to the music folder (as it is when it's elsewhere)."""
        try:
            return Path(path).relative_to(self.services.config.music_dir).as_posix()
        except ValueError:
            return path

    async def _set_result(self, take: Take, result: TakeResult, reason: str) -> None:
        await self.services.store.execute(
            "UPDATE track_results SET result = ?, reason = ?, finished_at = ? "
            "WHERE run_item_id = ? AND take_id = ?",
            (
                result,
                reason,
                iso_ms(self.services.clock.now()),
                self.job.run_item_id,
                take.take_id,
            ),
        )
        take.result, take.reason = result, reason
        self._take_done(take)

    def _take_done(self, take: Take) -> None:
        if self.now_playing is not None and self.now_playing.take_id == take.take_id:
            self.now_playing = None
        if not take.counted:
            return
        if take.result == "recorded":
            self._update_row(take, state="recorded", size_bytes=take.bytes)
        elif take.result == "skipped":
            state = "skipped_duplicate" if take.reason == "duplicate" else "skipped"
            self._update_row(take, state=state, reason=None if state != "skipped" else take.reason)
        else:
            self._update_row(take, state="failed", reason=take.reason)

    def _update_row(
        self,
        take: Take,
        *,
        state: str,
        size_bytes: int | None = None,
        reason: str | None = None,
    ) -> None:
        """Moves the take's row of the live table to `state` (adds one for a track not in the
        item's list: a whole item's, or one that wasn't matched)."""
        key = _position_key(take.track.position) if take.track is not None else take.identity
        index = self._row_of.get(key)
        if index is None:
            mpris_id = take.mpris_track_id
            self._add_row(
                key,
                RunTrack(
                    position=None,
                    track_id=mpris_id if mpris_id and _SPOTIFY_ID.match(mpris_id) else None,
                    title=take.title,
                    artists=[take.artist] if take.artist else [],
                    duration_ms=take.length_ms or None,
                    state="pending",
                    size_bytes=None,
                    reason=None,
                    take_id=None,
                ),
            )
            index = self._row_of[key]
        self._rows[index] = self._rows[index].model_copy(
            update={
                "state": state,
                "size_bytes": size_bytes,
                "reason": reason,
                "take_id": take.take_id,
            }
        )

    def _add_row(self, key: str, row: RunTrack) -> None:
        self._row_of.setdefault(key, len(self._rows))
        if self._row_of[key] == len(self._rows):
            self._rows.append(row)


def _position_key(position: int) -> str:
    """The live table's key for an entry of the item's list (a track can be listed twice)."""
    return f"#{position}"


def is_file_error(code: str) -> bool:
    """A Spytify `error` that means a take's file was lost (read, encode, rename)."""
    return code in _FILE_ERRORS
