"""The storage check: is /music a mounted, writable volume with room to record?

- **GET /api/storage** (routers/storage.py), shared by wizard step 6, Settings › Files and the
  run engine's pre-run check: `await services.storage.check()` gives the contract's `Storage`.
  `ok` needs /music mounted, writable and at least 2 GB free (`MIN_FREE_BYTES`); runs refuse to
  start below that. Under 5 GB (`LOW_SPACE_BYTES`, web-ui.md § Notifications) is logged as low.
- **LocalStorageProbe**, the real `ports.StorageProbe`: statvfs for the space,
  /proc/self/mountinfo for "a separate mount" and its host side, and a probe file written and
  removed for `writable`. All of it runs in a worker thread (`asyncio.to_thread`).

A folder owned by another uid (the NAS risk of plan § UGOS specifics, E2E step 9) shows up as
`not_writable` when the probe file can't be written; the log names the owner's uid and ours.
"""

import asyncio
import logging
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spotivault.api.models import Storage, Volume
from spotivault.ports import VolumeInfo

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

MIN_FREE_BYTES = 2_000_000_000  # a run refuses to start below this (openapi.yaml Storage)
LOW_SPACE_BYTES = 5_000_000_000  # "Music folder low on space (under 5 GB)", web-ui.md

MOUNTINFO = Path("/proc/self/mountinfo")
PROBE_PREFIX = ".spotivault-write-check-"

# A Docker volume that nobody named: /var/lib/docker/volumes/<64 hex>/_data. The image declares
# VOLUME /music, so an unmapped /music is one of these, not the container's own filesystem.
_ANONYMOUS_VOLUME = re.compile(r"/volumes/[0-9a-f]{64}/_data$")


# --- /proc/self/mountinfo ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MountEntry:
    """One line of /proc/self/mountinfo (proc(5)): the fields the storage check reads."""

    mount_point: str  # where it's mounted here, such as /music
    root: str  # the mounted folder, as a path inside its source file system
    fs_type: str
    source: str  # the device or file system source, such as /dev/sdb1

    @property
    def anonymous_volume(self) -> bool:
        """A Docker volume created because nothing was mapped there."""
        return bool(_ANONYMOUS_VOLUME.search(self.root))


def parse_mountinfo(text: str) -> list[MountEntry]:
    """Every mount in a mountinfo file's text, in its order. Lines it can't read are skipped."""
    entries = []
    for line in text.splitlines():
        fields = line.split(" ")
        try:
            separator = fields.index("-", 6)
            entries.append(
                MountEntry(
                    mount_point=_unescape(fields[4]),
                    root=_unescape(fields[3]),
                    fs_type=fields[separator + 1],
                    source=_unescape(fields[separator + 2]),
                )
            )
        except (ValueError, IndexError):
            continue
    return entries


def find_mount(entries: list[MountEntry], path: Path) -> MountEntry | None:
    """The mount at exactly `path`; the last one when mounts are stacked there."""
    found = None
    for entry in entries:
        if entry.mount_point == str(path):
            found = entry
    return found


def _unescape(field: str) -> str:
    # mountinfo writes a space, tab, newline and backslash in paths as \040, \011, \012, \134.
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


# --- The real probe ----------------------------------------------------------------------------


class LocalStorageProbe:
    """`ports.StorageProbe` for the container: the real file system, from a worker thread."""

    def __init__(self, mountinfo: Path = MOUNTINFO) -> None:
        self.mountinfo = mountinfo
        self._warned_anonymous: set[Path] = set()  # warned once each, not on every check

    async def volume(self, path: Path) -> VolumeInfo:
        return await asyncio.to_thread(self._volume, path)

    async def mount_source(self, path: Path) -> str | None:
        return await asyncio.to_thread(self._mount_source, path)

    # --- In the worker thread -------------------------------------------------------------------

    def _volume(self, path: Path) -> VolumeInfo:
        try:
            is_dir = path.is_dir()
        except OSError as exc:  # a parent folder that can't be searched, say
            log.warning("storage: can't look at %s: %s", path, exc)
            is_dir = False
        if not is_dir:
            return VolumeInfo(
                path=path,
                exists=False,
                mounted=False,
                writable=False,
                free_bytes=None,
                total_bytes=None,
            )
        free_bytes = total_bytes = None
        try:
            stats = os.statvfs(path)
            free_bytes = stats.f_bavail * stats.f_frsize  # what a user other than root can use
            total_bytes = stats.f_blocks * stats.f_frsize
        except OSError as exc:
            log.warning("storage: can't read the free space of %s: %s", path, exc)
        writable = self._can_write(path)
        if not writable:
            self._log_ownership(path)
        return VolumeInfo(
            path=path,
            exists=True,
            mounted=self._is_mounted(path),
            writable=writable,
            free_bytes=free_bytes,
            total_bytes=total_bytes,
        )

    def _can_write(self, path: Path) -> bool:
        """Writes a probe file and removes it, as this process's user."""
        probe = path / f"{PROBE_PREFIX}{os.getpid()}-{secrets.token_hex(4)}"
        try:
            fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            log.debug("storage: can't create a file in %s: %s", path, exc)
            return False
        wrote = True
        try:
            os.write(fd, b"spotivault\n")
        except OSError as exc:
            log.warning("storage: can't write to a file in %s: %s", path, exc)
            wrote = False
        finally:
            os.close(fd)
        try:
            probe.unlink()
        except OSError as exc:
            # Spytify renames and removes its working files, so this counts as not writable.
            log.warning("storage: can't remove the probe file %s: %s", probe, exc)
            return False
        return wrote

    def _log_ownership(self, path: Path) -> None:
        """Says whose folder it is, for the NAS case: a share owned by another user."""
        ours = os.geteuid()
        try:
            stat = os.stat(path)
        except OSError:
            log.warning("storage: %s isn't writable by uid %d", path, ours)
            return
        if stat.st_uid != ours:
            log.warning(
                "storage: %s isn't writable by spotivault (uid %d): it belongs to uid %d, mode %o."
                " Give uid %d, or Everyone, write access to the shared folder.",
                path,
                ours,
                stat.st_uid,
                stat.st_mode & 0o7777,
                ours,
            )
        else:
            log.warning(
                "storage: %s isn't writable by spotivault (uid %d), although it owns it (mode %o)",
                path,
                ours,
                stat.st_mode & 0o7777,
            )

    def _entries(self) -> list[MountEntry] | None:
        try:
            return parse_mountinfo(self.mountinfo.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            log.debug("storage: can't read %s: %s", self.mountinfo, exc)
            return None

    def _is_mounted(self, path: Path) -> bool:
        resolved = Path(os.path.realpath(path))
        entries = self._entries()
        if entries is None:
            return os.path.ismount(resolved)
        entry = find_mount(entries, resolved)
        if entry is None:
            return False
        if entry.anonymous_volume:
            if path not in self._warned_anonymous:
                self._warned_anonymous.add(path)
                log.warning(
                    "storage: %s is an anonymous Docker volume: nothing is mapped there, so "
                    "files stay in Docker's own storage. Map it to a shared folder.",
                    path,
                )
            return False
        return True

    def _mount_source(self, path: Path) -> str | None:
        """The mounted folder as a path in its source file system (for a bind mount, the host
        folder, relative to the file system it's on: `/Music` for `/volume6/Music`), or the
        source itself for a whole one. The host's own mount points aren't visible from here."""
        entries = self._entries()
        if entries is None:
            return None
        entry = find_mount(entries, Path(os.path.realpath(path)))
        if entry is None:
            return None
        return entry.root if entry.root != "/" else entry.source


# --- The service -------------------------------------------------------------------------------


class StorageService:
    """The storage check. Built by services.py as `services.storage`."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self._last_problem: str | None = None
        self._last_low: bool = False

    async def check(self) -> Storage:
        """Checks /music and /config now (GET /api/storage, wizard step 6, the pre-run check).

        Writes and removes a probe file in each. Logs when /music's state changes.
        """
        config = self.services.config
        probe = self.services.ports.storage
        music = await probe.volume(config.music_dir)
        conf = await probe.volume(config.config_dir)
        storage = Storage(
            music=_volume(music),
            config=_volume(conf),
            min_free_bytes=MIN_FREE_BYTES,
            ok=_music_ok(music),
        )
        self._log_changes(storage)
        return storage

    def _log_changes(self, storage: Storage) -> None:
        problem = storage_problem(storage)
        if problem != self._last_problem:
            if problem is not None:
                log.warning("storage: %s", problem)
            elif self._last_problem is not None:
                log.info("storage: %s is ready", storage.music.path)
            self._last_problem = problem
        free = storage.music.free_bytes
        low = storage.ok and free is not None and free < LOW_SPACE_BYTES
        if low and not self._last_low:
            log.warning(
                "storage: %s is low on space: %s free", storage.music.path, format_bytes(free)
            )
        self._last_low = low


def _volume(info: VolumeInfo) -> Volume:
    if not info.exists:
        error = "not_found"
    elif not info.mounted:
        error = "not_mounted"
    elif not info.writable:
        error = "not_writable"
    else:
        error = None
    return Volume(
        path=str(info.path),
        mounted=info.exists and info.mounted,
        writable=info.exists and info.writable,
        free_bytes=info.free_bytes,
        total_bytes=info.total_bytes,
        error=error,
    )


def _music_ok(info: VolumeInfo) -> bool:
    return (
        info.exists
        and info.mounted
        and info.writable
        and info.free_bytes is not None
        and info.free_bytes >= MIN_FREE_BYTES
    )


def storage_problem(storage: Storage) -> str | None:
    """Why /music can't be recorded to, in a sentence for wizard step 6, the log and the run
    engine's refusal; None when `storage.ok`."""
    music = storage.music
    if music.error == "not_found":
        return f"{music.path} doesn't exist. Map it to a shared folder in the UGOS Docker app."
    if music.error == "not_mounted":
        return (
            f"{music.path} isn't mapped to a folder on the NAS, so recordings would stay inside "
            "Docker. Map it to a shared folder in the UGOS Docker app."
        )
    if music.error == "not_writable":
        uid = os.geteuid()
        return (
            f"spotivault (uid {uid}) can't write to {music.path}. Give uid {uid}, or Everyone, "
            "write access to the shared folder."
        )
    if music.free_bytes is None:
        return f"The free space in {music.path} can't be read."
    if music.free_bytes < storage.min_free_bytes:
        return (
            f"{music.path} has {format_bytes(music.free_bytes)} free. Recording needs at least "
            f"{format_bytes(storage.min_free_bytes)}."
        )
    return None


def format_bytes(count: int) -> str:
    """Bytes for people, in decimal units as the UI shows them: '1.2 GB'."""
    for unit, size in (("TB", 10**12), ("GB", 10**9), ("MB", 10**6), ("kB", 10**3)):
        if count >= size:
            return f"{count / size:.1f} {unit}"
    return f"{count} B"
