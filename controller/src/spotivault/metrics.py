"""Run metrics: one sample every 60 s while a run is going, into `run_metrics` (plan § Long runs).

Owner: **history-files-metrics** (controller/ARCHITECTURE.md § S6's parts). Built by
services.py as `services.metrics`; its background task is registered in the constructor.

Each sample (contracts/schema.sql `run_metrics`, plus migration 003's `loop_lag_max_ms`):
- **RSS and CPU** of the Spotify processes (every process whose /proc/<pid>/comm is `spotify`
  or that runs from config.spotify_dir, summed), spytifyd (`services.runs.recorder_pid()`; NULL
  between items) and the controller (os.getpid()). RSS from /proc/<pid>/status VmRSS; CPU % over
  the interval from /proc/<pid>/stat utime + stime against os.sysconf("SC_CLK_TCK"), 100 = one
  core. The first sample of a run has no interval: CPU NULL.
- **The client's cache size:** config.home_dir / ".cache" / "spotify", summed file sizes.
- **Free space** in /music and /config: `services.ports.storage.volume(path).free_bytes` (the
  fake probe answers in fake mode).
- **The Web API request rate:** `services.webapi_usage.requests_last_30s()`.
- **The loop lag:** `services.loopwatch.take_max()`, in ms.
- `at` from services.clock (iso_ms); `run_id` from `services.runs.active()`.

All /proc and folder reads go through asyncio.to_thread; a value that can't be read is NULL,
never an error (fake mode has no Spotify processes). A failing sample is logged and skipped:
the background task must never raise.

Choices where the specs are silent (reported to the user):
- A group with no process (the client isn't running, or no recorder) has NULL RSS and CPU.
- A cache folder that doesn't exist is 0 bytes; one that can't be read is NULL.
- CPU is per process: a process that appeared since the last sample adds nothing to the group's
  CPU until the next one, and a group with no process in both samples is NULL.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from spotivault.clock import iso_ms

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

SAMPLE_INTERVAL_S = 60.0
PROC_ROOT = Path("/proc")
SPOTIFY_COMM = "spotify"


@dataclass(frozen=True, slots=True)
class MetricsSample:
    """One `run_metrics` row."""

    run_id: int
    at: str  # iso_ms
    spotify_rss_bytes: int | None
    spotify_cpu_pct: float | None
    spytifyd_rss_bytes: int | None
    spytifyd_cpu_pct: float | None
    controller_rss_bytes: int | None
    controller_cpu_pct: float | None
    client_cache_bytes: int | None
    music_free_bytes: int | None
    config_free_bytes: int | None
    webapi_requests_30s: int | None
    loop_lag_max_ms: int | None


@dataclass(frozen=True, slots=True)
class ProcInfo:
    """What /proc says about one process: its name, its executable, its memory and its CPU
    time so far (utime + stime, in clock ticks)."""

    pid: int
    comm: str
    exe: Path | None
    rss_bytes: int | None
    ticks: int | None


@dataclass(slots=True)
class _Readings:
    """One round of /proc reads: the Spotify group, spytifyd and the controller."""

    spotify: list[ProcInfo] = field(default_factory=list)
    spytifyd: list[ProcInfo] = field(default_factory=list)
    controller: list[ProcInfo] = field(default_factory=list)


# --- Reading /proc (blocking: run through asyncio.to_thread) ----------------------------------


def list_pids(proc_root: Path) -> list[int]:
    """The process ids under /proc."""
    try:
        with os.scandir(proc_root) as entries:
            return [int(entry.name) for entry in entries if entry.name.isdigit()]
    except OSError:
        return []


def read_process(proc_root: Path, pid: int) -> ProcInfo | None:
    """One process's facts, or None when it's gone. A part that can't be read is None in it."""
    base = proc_root / str(pid)
    try:
        comm = (base / "comm").read_text(encoding="utf-8", errors="replace").strip()
        stat = (base / "stat").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None  # the process exited between the listing and the read
    exe: Path | None = None
    try:
        exe = Path(os.readlink(base / "exe"))
    except OSError:
        exe = None  # not ours to read (another user's process, or gone)
    return ProcInfo(
        pid=pid,
        comm=comm,
        exe=exe,
        rss_bytes=_rss_bytes(base / "status"),
        ticks=_ticks(stat),
    )


def _rss_bytes(status_file: Path) -> int | None:
    """VmRSS from /proc/<pid>/status ("VmRSS:   12345 kB"), in bytes."""
    try:
        text = status_file.read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            fields = line.split()
            if len(fields) >= 2 and fields[1].isdigit():
                return int(fields[1]) * 1024
    return None


def _ticks(stat: str) -> int | None:
    """utime + stime from /proc/<pid>/stat. The name in field 2 may hold spaces and brackets, so
    the fields are counted from the last ')'. utime and stime are fields 14 and 15 (1-based)."""
    end = stat.rfind(")")
    if end < 0:
        return None
    fields = stat[end + 2 :].split()
    if len(fields) < 13:
        return None
    try:
        return int(fields[11]) + int(fields[12])
    except ValueError:
        return None


def is_spotify(proc: ProcInfo, spotify_dir: Path) -> bool:
    """The Spotify client's processes: named `spotify`, or running from its install folder."""
    if proc.comm == SPOTIFY_COMM:
        return True
    return proc.exe is not None and proc.exe.is_relative_to(spotify_dir)


def read_all(
    proc_root: Path, spotify_dir: Path, spytifyd_pid: int | None, own_pid: int
) -> _Readings:
    """Every reading one sample needs, in one blocking pass."""
    readings = _Readings()
    for pid in list_pids(proc_root):
        proc = read_process(proc_root, pid)
        if proc is not None and is_spotify(proc, spotify_dir):
            readings.spotify.append(proc)
    if spytifyd_pid is not None:
        proc = read_process(proc_root, spytifyd_pid)
        if proc is not None:
            readings.spytifyd.append(proc)
    own = read_process(proc_root, own_pid)
    if own is not None:
        readings.controller.append(own)
    return readings


def tree_bytes(folder: Path) -> int | None:
    """The summed size of the files under `folder`: 0 when there's no such folder, None when it
    can't be read."""
    if not folder.exists():
        return 0
    total = 0
    try:
        for root, _dirs, files in os.walk(folder, onerror=_raise):
            for name in files:
                total += os.lstat(os.path.join(root, name)).st_size
    except OSError:
        return None
    return total


def _raise(error: OSError) -> None:
    raise error


# --- The service


class MetricsService:
    """Built by services.py as `services.metrics`."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        # Where /proc is, and the clock's ticks per second: attributes so tests can point them at
        # a fake /proc tree.
        self.proc_root = PROC_ROOT
        self.clk_tck = os.sysconf("SC_CLK_TCK")
        # The CPU readings of the last sample: the run it was for, the monotonic time, and each
        # process's ticks. A new run starts without an interval, so its first sample has no CPU.
        self._last_run_id: int | None = None
        self._last_monotonic: float | None = None
        self._last_ticks: dict[int, int] = {}
        services.add_background("metrics", self.watch)

    async def sample(self, run_id: int) -> MetricsSample:
        """Takes one sample now (not stored)."""
        services = self.services
        config = services.config
        now = services.clock.now()
        spytifyd_pid = services.runs.recorder_pid()
        readings = await asyncio.to_thread(
            read_all, self.proc_root, config.spotify_dir, spytifyd_pid, os.getpid()
        )
        monotonic = services.clock.monotonic()
        interval = self._interval(run_id, monotonic)
        spotify_rss, spotify_cpu = self._group(readings.spotify, interval)
        spytifyd_rss, spytifyd_cpu = self._group(readings.spytifyd, interval)
        controller_rss, controller_cpu = self._group(readings.controller, interval)
        self._remember(
            run_id, monotonic, [*readings.spotify, *readings.spytifyd, *readings.controller]
        )

        return MetricsSample(
            run_id=run_id,
            at=iso_ms(now),
            spotify_rss_bytes=spotify_rss,
            spotify_cpu_pct=spotify_cpu,
            spytifyd_rss_bytes=spytifyd_rss,
            spytifyd_cpu_pct=spytifyd_cpu,
            controller_rss_bytes=controller_rss,
            controller_cpu_pct=controller_cpu,
            client_cache_bytes=await asyncio.to_thread(
                tree_bytes, config.home_dir / ".cache" / "spotify"
            ),
            music_free_bytes=await self._free_bytes(config.music_dir),
            config_free_bytes=await self._free_bytes(config.config_dir),
            webapi_requests_30s=await self._webapi_rate(),
            loop_lag_max_ms=round(services.loopwatch.take_max() * 1000),
        )

    async def store(self, sample: MetricsSample) -> None:
        """Inserts one sample into run_metrics."""
        await self.services.store.execute(
            "INSERT INTO run_metrics (run_id, at, spotify_rss_bytes, spotify_cpu_pct, "
            "spytifyd_rss_bytes, spytifyd_cpu_pct, controller_rss_bytes, controller_cpu_pct, "
            "client_cache_bytes, music_free_bytes, config_free_bytes, webapi_requests_30s, "
            "loop_lag_max_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sample.run_id,
                sample.at,
                sample.spotify_rss_bytes,
                sample.spotify_cpu_pct,
                sample.spytifyd_rss_bytes,
                sample.spytifyd_cpu_pct,
                sample.controller_rss_bytes,
                sample.controller_cpu_pct,
                sample.client_cache_bytes,
                sample.music_free_bytes,
                sample.config_free_bytes,
                sample.webapi_requests_30s,
                sample.loop_lag_max_ms,
            ),
        )

    async def watch(self) -> None:
        """Background task: every SAMPLE_INTERVAL_S on services.clock, while a run is going,
        `store(await sample(run_id))`. Never raises."""
        while True:
            await self.services.clock.sleep(SAMPLE_INTERVAL_S)
            try:
                active = self.services.runs.active()
                if active is not None:
                    await self.store(await self.sample(active.run_id))
            except Exception:
                log.exception("a run metrics sample failed; skipped")

    # --- helpers

    def _interval(self, run_id: int, monotonic: float) -> float | None:
        """Seconds since the last sample, when it was for this run; None otherwise."""
        if self._last_monotonic is None or self._last_run_id != run_id:
            return None
        elapsed = monotonic - self._last_monotonic
        return elapsed if elapsed > 0 else None

    def _group(
        self, procs: list[ProcInfo], interval: float | None
    ) -> tuple[int | None, float | None]:
        """(RSS bytes, CPU %) of one group: RSS summed over its processes, CPU over the ones seen
        in the last sample too. None where there's nothing to report."""
        rss_values = [proc.rss_bytes for proc in procs if proc.rss_bytes is not None]
        rss = sum(rss_values) if rss_values else None
        cpu: float | None = None
        if interval is not None:
            deltas = [
                max(0, proc.ticks - self._last_ticks[proc.pid])
                for proc in procs
                if proc.ticks is not None and proc.pid in self._last_ticks
            ]
            if deltas:
                cpu = 100.0 * sum(deltas) / self.clk_tck / interval
        return rss, cpu

    def _remember(self, run_id: int, monotonic: float, procs: list[ProcInfo]) -> None:
        """Keeps this sample's ticks for the next one's CPU."""
        self._last_run_id = run_id
        self._last_monotonic = monotonic
        self._last_ticks = {proc.pid: proc.ticks for proc in procs if proc.ticks is not None}

    async def _free_bytes(self, folder: Path) -> int | None:
        """Free space on the volume of `folder`, or None when the probe can't say."""
        try:
            info = await self.services.ports.storage.volume(folder)
        except Exception:
            log.warning("free space of %s couldn't be read", folder, exc_info=True)
            return None
        return info.free_bytes

    async def _webapi_rate(self) -> int | None:
        """The Web API requests in the last 30 s, or None when the usage log can't be read."""
        try:
            return await self.services.webapi_usage.requests_last_30s()
        except Exception:
            log.warning("the Web API request count couldn't be read", exc_info=True)
            return None
