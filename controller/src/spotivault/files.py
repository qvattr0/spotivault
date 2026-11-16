"""Files in the music folder the controller writes or tidies: the `.m3u` playlists, and the stale
working files Spytify leaves behind.

Owner: **history-files-metrics** (controller/ARCHITECTURE.md § S6's parts). Built by
services.py as `services.files`. Frozen interface: `write_m3u` and `cleanup_stale` (the item and
run engines call them) and the two pure helpers.

**The .m3u** (design.md § Run flow step 7; web-ui.md § Settings › Files "Playlist files"; plan
"`.m3u` paths: relative to the `.m3u` file"):
- Only playlists and Liked Songs, never albums; only while the setting `write_m3u` is on.
- `<music>/Playlists/<name>.m3u`, `name` made safe for a file name (m3u_file_name). The name is
  taken when another item's `m3u_path` holds it, or a file the controller didn't write is there
  (yours, or another tool's): then " (<first 6 characters of its id>)", then " (<its id>)"; none
  free, no .m3u. The path written last is kept in `items.m3u_path` (migration 003); a renamed
  playlist's old file is removed. Only files an `items.m3u_path` names are ever replaced or
  removed.
- Content: `#EXTM3U`, then per recorded track `#EXTINF:<whole seconds>,<artist> - <title>` and its
  path relative to the .m3u's folder (`../fakename/Elsewhere/05 - Last Hours.m4a`), POSIX
  separators, UTF-8, "\\n" line ends.
- **Which tracks, in which order:** missing_only items: the stored track list in Web API order
  (item_tracks.position), each track whose `tracks.spytify_key` has a file in
  `services.matching.index()` (Spytify's index is the authority: it has the path). A track that
  became unplayable since keeps its place while its file is there; local files, episodes and
  empty entries are left out. Whole items: the last clean full pass's order
  (observed_tracks.ordinal), then the takes of every later run item in the order they started,
  so tracks recorded since are added at the end (with no clean pass: every run item's takes);
  each key looked up the same way. A track without a file is left out.
- Written atomically (a temporary file in the same folder, then os.replace), with
  `config.umask_bits` applied to the file and to a new Playlists folder (UMASK is for /music).
  File work through asyncio.to_thread.

**File modes** (docs/upstream/spytify-bugs.md #7): Spytify 2.0.2 tags AAC, MP3 and FLAC files
into a temporary file made with mode 0600 and renames it into place, so UMASK never reaches them.
After each item, `fix_modes` gives the files it recorded 0666 less UMASK, as Spytify's WAVs and
the .m3u get. Only those files: folders (Spytify makes them 0755) and anything else are left.

**Stale files** (docs/upstream/spytify-bugs.md #4 and #5): Spytify's own leftovers only, older than
60 s, removed only while no recorder runs (the callers make sure): WAVs in `<music>/.spytify/`
itself (not in a `.spytify` folder further down: another Spytify's), and `.part` files of its
names (`<final>.part`, final ending in .mp3, .m4a, .flac or .wav), never another program's
download. With `folders` None, the whole music folder is walked (start-up recovery); otherwise
only `.spytify/` and those folders (between items, the item engine passes none). A recorder ended
by a signal may leave a .part where it was encoding (bug 5): `recorder_killed()` makes the first
cleanup at least 60 s later walk the whole folder instead.

Choices where the specs are silent (reported to the user):
- Which mode a whole or missing_only item is in: the mode of its newest `run_items` row, else
  whole when it has no item access. Whole items' order: the newest run item that has take
  results, each key from the track's own key when it was matched, else from its artist and title.
- A file with the name of no item's `items.m3u_path` is never overwritten: the playlist gets the
  next free name (cautious: it may be yours).
- The label in #EXTINF is every artist joined with ", " (as Spotify shows them).
"""

import asyncio
import json
import logging
import os
import re
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spotivault.matching import track_key

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

STALE_AFTER_S = 60.0
PLAYLISTS_FOLDER = "Playlists"
# The file types Spytify encodes to (encode.format mp3, aac, flac, wav): its .part files are
# `<name><one of these>.part`.
SPYTIFY_PART_SUFFIXES = (".mp3.part", ".m4a.part", ".flac.part", ".wav.part")
SPYTIFY_FOLDER = ".spytify"
MAX_NAME_BYTES = 200
DEFAULT_NAME = "Playlist"

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class CleanupResult:
    wavs_removed: int
    parts_removed: int


def m3u_file_name(name: str) -> str:
    """A playlist name as a safe file name, without the extension: no `/`, `\\`, control
    characters or leading dots; trimmed; at most 200 bytes of UTF-8; "Playlist" if empty."""
    text = name.replace("/", "_").replace("\\", "_")
    text = _CONTROL_CHARACTERS.sub(" ", text)
    text = text.strip().lstrip(" .").rstrip()
    text = _truncate_utf8(text, MAX_NAME_BYTES).rstrip()
    return text or DEFAULT_NAME


def _truncate_utf8(text: str, limit: int) -> str:
    """`text` cut to at most `limit` bytes of UTF-8, never through a character."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def m3u_entry(m3u_path: Path, track_path: Path) -> str:
    """`track_path` relative to the .m3u's folder, with POSIX separators (`../A/B/01 - X.m4a`)."""
    return os.path.relpath(track_path, m3u_path.parent).replace(os.sep, "/")


@dataclass(frozen=True, slots=True)
class _Entry:
    """One track of a playlist, before its file is looked up: Spytify's key and its label."""

    key: str
    label: str  # "<artist> - <title>"
    duration_ms: int | None


class FilesService:
    """Built by services.py as `services.files`."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        # When a recorder was killed: the first cleanup from then (its .part is stale by then)
        # walks the whole music folder. A timestamp on services.clock's wall clock.
        self._walk_due_at: float | None = None

    def recorder_killed(self) -> None:
        """A recorder ended by a signal (bug 5): see the module docstring, "Stale files"."""
        due = self.services.clock.now().timestamp() + STALE_AFTER_S
        if self._walk_due_at is None:
            self._walk_due_at = due

    async def write_m3u(self, item_id: str) -> Path | None:
        """Writes (or rewrites) the item's .m3u and returns its path; None when it gets none
        (an album, the setting off, nothing recorded yet)."""
        services = self.services
        if not await services.settings.get_value("write_m3u"):
            return None
        item = await services.store.fetchone(
            "SELECT id, kind, name, item_access, m3u_path FROM items WHERE id = ?", (item_id,)
        )
        if item is None or item["kind"] == "album":
            return None
        mode = await self._mode(item_id, item["item_access"])
        entries = await self._entries(item_id, mode)
        index = await services.matching.index()
        found: list[tuple[_Entry, Path]] = []
        seen: set[str] = set()
        for entry in entries:
            path = index.path(entry.key)
            if path is None or entry.key in seen:
                continue  # not recorded (or no file now), or already listed
            seen.add(entry.key)
            found.append((entry, Path(path)))
        if not found:
            return None

        music = services.config.music_dir
        relative = await self._relative_path(item_id, item["name"], item["m3u_path"])
        if relative is None:
            log.warning(
                "files: no free .m3u name for %s (%s): files you made have them",
                item_id,
                item["name"],
            )
            return None
        target = music / relative
        text = _m3u_text(target, found)
        umask = services.config.umask_bits
        await asyncio.to_thread(_write_atomic, target, text, umask)

        old = item["m3u_path"]
        await services.store.execute(
            "UPDATE items SET m3u_path = ? WHERE id = ?", (relative, item_id)
        )
        if old is not None and old != relative:
            await asyncio.to_thread(_remove_quietly, music / old)
        return target

    async def fix_modes(self, paths: Iterable[str]) -> int:
        """Gives each recorded file (a path relative to the music folder, or absolute inside it)
        mode 0666 less UMASK (module docstring). A file outside the music folder, missing, or not
        a regular file is skipped. Returns how many changed."""
        music = self.services.config.music_dir
        mode = 0o666 & ~self.services.config.umask_bits
        files = [music / path for path in paths]
        return await asyncio.to_thread(_fix_modes, music, files, mode)

    async def cleanup_stale(self, folders: Iterable[Path] | None = None) -> CleanupResult:
        """Removes stale WAVs and .part files (module docstring)."""
        now = self.services.clock.now().timestamp()
        music = self.services.config.music_dir
        wanted = None if folders is None else list(folders)
        if wanted is not None and self._walk_due_at is not None and now >= self._walk_due_at:
            log.info("files: a recorder was killed: looking for its .part files everywhere")
            wanted = None
        if wanted is None:
            self._walk_due_at = None
        return await asyncio.to_thread(_cleanup, music, wanted, now)

    # --- The .m3u's inputs ----------------------------------------------------------------------

    async def _mode(self, item_id: str, item_access: int) -> str:
        """'missing_only' or 'whole': the planned mode of the newest run item, else by access."""
        row = await self.services.store.fetchone(
            "SELECT mode FROM run_items WHERE item_id = ? AND mode IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (item_id,),
        )
        if row is not None:
            return row["mode"]
        return "missing_only" if item_access == 1 else "whole"

    async def _entries(self, item_id: str, mode: str) -> list[_Entry]:
        """The item's tracks in playlist order, before the index lookup."""
        store = self.services.store
        if mode == "missing_only":
            # Unplayable now (pulled by its label) but recorded: still in the playlist.
            rows = await store.fetchall(
                "SELECT t.spytify_key, t.artists, t.name, t.duration_ms "
                "FROM item_tracks it JOIN tracks t ON t.id = it.track_id "
                "WHERE it.item_id = ? AND (it.unplayable_reason IS NULL "
                "OR it.unplayable_reason = 'not_playable') ORDER BY it.position",
                (item_id,),
            )
            return [
                _Entry(row["spytify_key"], _label(row["artists"], row["name"]), row["duration_ms"])
                for row in rows
            ]
        # A length is the matched track's when there is one, else the one the pass saw.
        observed = await store.fetchall(
            "SELECT o.spytify_key, o.artist, o.title, coalesce(t.duration_ms, o.length_ms) "
            "AS duration_ms FROM observed_tracks o LEFT JOIN tracks t ON t.id = o.track_id "
            "WHERE o.item_id = ? ORDER BY o.ordinal",
            (item_id,),
        )
        entries = [
            _Entry(row["spytify_key"], f"{row['artist']} - {row['title']}", row["duration_ms"])
            for row in observed
        ]
        # Then what was heard since (every run item when there's no clean pass), in the order
        # it started: tracks recorded after the last clean pass go at the end.
        pass_run = await store.fetchval(
            "SELECT MAX(run_id) FROM observed_tracks WHERE item_id = ?", (item_id,)
        )
        takes = await store.fetchall(
            "SELECT tr.artist, tr.title, coalesce(t.duration_ms, tr.length_ms) AS duration_ms, "
            "t.spytify_key AS track_key "
            "FROM run_items ri JOIN track_results tr ON tr.run_item_id = ri.id "
            "LEFT JOIN tracks t ON t.id = tr.track_id "
            "WHERE ri.item_id = ? AND ri.run_id > ? ORDER BY ri.id, tr.started_at, tr.id",
            (item_id, pass_run if pass_run is not None else -1),
        )
        entries += [
            _Entry(
                row["track_key"] or track_key(row["artist"], row["title"]),
                f"{row['artist']} - {row['title']}",
                row["duration_ms"],
            )
            for row in takes
        ]
        return entries

    async def _relative_path(self, item_id: str, name: str, ours: str | None) -> str | None:
        """`Playlists/<name>.m3u`, else with " (<6 characters of the id>)", else " (<the id>)":
        the first that is this item's own file (`ours`), or that no other item holds and no
        file is at. None when every one is taken (module docstring)."""
        base = m3u_file_name(name)
        rows = await self.services.store.fetchall(
            "SELECT m3u_path FROM items WHERE m3u_path IS NOT NULL AND id <> ?", (item_id,)
        )
        held = {row["m3u_path"] for row in rows}
        music = self.services.config.music_dir
        for suffix in ("", f" ({item_id[:6]})", f" ({item_id})"):
            relative = f"{PLAYLISTS_FOLDER}/{base}{suffix}.m3u"
            if relative == ours:
                return relative
            if relative in held:
                continue
            if not await asyncio.to_thread(os.path.lexists, music / relative):
                return relative
        return None


def _label(artists_json: str, name: str) -> str:
    """ "<artist> - <title>", every artist joined with ", " (tracks.artists is a JSON array)."""
    artists = json.loads(artists_json)
    return f"{', '.join(artists)} - {name}"


def _m3u_text(target: Path, found: list[tuple[_Entry, Path]]) -> str:
    """The playlist's text: #EXTM3U, then an #EXTINF and a relative path per track."""
    lines = ["#EXTM3U"]
    for entry, track in found:
        seconds = -1 if entry.duration_ms is None else entry.duration_ms // 1000
        label = entry.label.replace("\r", " ").replace("\n", " ")
        lines.append(f"#EXTINF:{seconds},{label}")
        lines.append(m3u_entry(target, track))
    return "\n".join(lines) + "\n"


def _write_atomic(target: Path, text: str, umask: int) -> None:
    """Writes `text` to `target` through a temporary file in the same folder, then replaces it.
    The file gets 0666 less the umask (and a new Playlists folder 0777 less it), so a NAS share
    stays readable to its users. Blocking: run it with asyncio.to_thread."""
    folder = target.parent
    if not folder.is_dir():
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o777 & ~umask)
    fd, temp_name = tempfile.mkstemp(dir=folder, prefix=f".{target.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.chmod(temp_name, 0o666 & ~umask)
        os.replace(temp_name, target)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temp_name)
        raise


def _fix_modes(music: Path, files: list[Path], mode: int) -> int:
    """chmod each regular file under `music` to `mode` when it differs. Blocking: run it with
    asyncio.to_thread. A file it can't change is logged and skipped."""
    changed = 0
    root = music.resolve()
    for path in files:
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(root) or not resolved.is_file():
                continue
            if resolved.stat().st_mode & 0o7777 != mode:
                os.chmod(resolved, mode)
                changed += 1
        except OSError as exc:
            log.warning("files: can't set the mode of %s: %s", path, exc)
    return changed


def _remove_quietly(path: Path) -> None:
    """Removes a file, if it's there. A failure is logged, never raised."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError:
        log.warning("could not remove the old playlist file %s", path, exc_info=True)


# --- Stale files ---------------------------------------------------------------------------------


def _cleanup(music: Path, folders: list[Path] | None, now: float) -> CleanupResult:
    """Removes the stale files in the folders to tidy (see the module docstring). Blocking."""
    spytify = music / SPYTIFY_FOLDER
    if folders is None:
        scanned = [Path(root) for root, _dirs, _files in os.walk(music)]
    else:
        scanned = [spytify, *folders]
    wavs = parts = 0
    for folder in dict.fromkeys(scanned):  # each folder once, in order
        if folder == spytify:
            wavs += _remove_stale_in(folder, now, (".wav",))
        parts += _remove_stale_in(folder, now, SPYTIFY_PART_SUFFIXES)
    if wavs or parts:
        log.info("removed %d stale WAV and %d partial file(s) from the music folder", wavs, parts)
    return CleanupResult(wavs_removed=wavs, parts_removed=parts)


def _remove_stale_in(folder: Path, now: float, suffixes: tuple[str, ...]) -> int:
    """Removes the files in `folder` (not below it) whose names end in one of `suffixes`, and
    that haven't changed for STALE_AFTER_S. Returns how many went. A folder that's gone counts
    as none."""
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return 0
    removed = 0
    for entry in entries:
        if not entry.name.endswith(suffixes) or not entry.is_file(follow_symlinks=False):
            continue
        try:
            if now - entry.stat(follow_symlinks=False).st_mtime < STALE_AFTER_S:
                continue  # possibly still being written
            os.unlink(entry.path)
            removed += 1
        except FileNotFoundError:
            continue  # gone meanwhile
        except OSError:
            log.warning("could not remove the stale file %s", entry.path, exc_info=True)
    return removed
