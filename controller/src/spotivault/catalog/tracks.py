"""Storing an item's track list: the `tracks` and `item_tracks` tables (contracts/schema.sql).

The catalog refresh (playlists, Liked Songs) and adding albums both end with a track list in Web
API order. `replace_item_tracks` writes it in one go, inside the caller's transaction:

    def save(conn: sqlite3.Connection) -> TrackListSummary:
        summary = replace_item_tracks(conn, item_id, entries, now)
        conn.execute("UPDATE items SET total = ? WHERE id = ?", (summary.playable, item_id))
        return summary

    summary = await services.store.transaction(save)

Entries that can't be recorded stay in the list, so positions match Spotify's numbering, but are
marked with why (design.md § Run flow step 1): a local file, an episode, an entry with no `item`,
or `is_playable: false` under `market=from_token`.

The catalog refresh, the Library and the Albums page all call it.
"""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from spotivault.matching import web_track_key
from spotivault.ports import Track

type UnplayableReason = Literal["local", "episode", "no_item", "not_playable"]


@dataclass(frozen=True, slots=True)
class ListedTrack:
    """One entry of a track list, in Web API order: a playlist entry, a Liked Songs entry or an
    album track. `track` is None for a playlist entry with no `item`."""

    track: Track | None
    added_at: str | None = None  # the entry's added_at; None for album tracks


@dataclass(frozen=True, slots=True)
class TrackListSummary:
    """What a stored track list adds up to. `playable` is the item's `total`."""

    entries: int
    playable: int
    playable_ms: int  # the playable tracks' duration_ms, summed


def unplayable_reason(track: Track | None) -> UnplayableReason | None:
    """Why an entry can't be recorded, or None when it can. In this order: no `item`, a local
    file, an episode, no id (treated as no item), `is_playable: false`. `is_playable` None (the
    answer didn't say) counts as playable."""
    if track is None:
        return "no_item"
    if track.is_local:
        return "local"
    if track.is_episode:
        return "episode"
    if track.id is None:
        return "no_item"
    if track.is_playable is False:
        return "not_playable"
    return None


def replace_item_tracks(
    conn: sqlite3.Connection, item_id: str, entries: Sequence[ListedTrack], fetched_at: str
) -> TrackListSummary:
    """Replaces the item's whole track list, on the database thread, in the caller's transaction.

    Each track with an id is upserted into `tracks`, with its Spytify key (matching.track_key of
    the first artist and the title). Then the item's `item_tracks` rows are rewritten, position 0
    first. Local files keep no `tracks` row (they have no id), so their row has no track_id.
    `fetched_at` is an `iso_ms` time. The item's row must exist (foreign key).
    """
    conn.execute("DELETE FROM item_tracks WHERE item_id = ?", (item_id,))
    playable = 0
    playable_ms = 0
    track_rows = []
    entry_rows = []
    for position, entry in enumerate(entries):
        track = entry.track
        reason = unplayable_reason(track)
        track_id = track.id if track is not None and not track.is_local else None
        if track is not None and track_id is not None:
            track_rows.append(
                (
                    track_id,
                    track.uri,
                    track.name,
                    json.dumps(list(track.artists), ensure_ascii=False),
                    track.album_id,
                    track.album_name,
                    track.track_number,
                    track.disc_number,
                    max(0, track.duration_ms),
                    web_track_key(track),
                    fetched_at,
                )
            )
        if reason is None and track is not None:
            playable += 1
            playable_ms += max(0, track.duration_ms)
        entry_rows.append(
            (item_id, position, track_id, 1 if reason is None else 0, reason, entry.added_at)
        )
    conn.executemany(
        "INSERT INTO tracks (id, uri, name, artists, album_id, album_name, track_number, "
        "disc_number, duration_ms, spytify_key, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET uri = excluded.uri, name = excluded.name, "
        "artists = excluded.artists, album_id = excluded.album_id, "
        "album_name = excluded.album_name, track_number = excluded.track_number, "
        "disc_number = excluded.disc_number, duration_ms = excluded.duration_ms, "
        "spytify_key = excluded.spytify_key, fetched_at = excluded.fetched_at",
        track_rows,
    )
    conn.executemany(
        "INSERT INTO item_tracks (item_id, position, track_id, playable, unplayable_reason, "
        "added_at) VALUES (?, ?, ?, ?, ?, ?)",
        entry_rows,
    )
    return TrackListSummary(entries=len(entries), playable=playable, playable_ms=playable_ms)
