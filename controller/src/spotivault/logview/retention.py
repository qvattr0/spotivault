"""Log retention: 14 days or 50 MB, whichever comes first (web-ui.md § Logs tab; Q23). Blocking:
run it in a thread.

s6-log rotates each service's log by size only (`n10 s1048576` in svc-log: 10 files of 1 MB),
and Spytify's item logs aren't rotated at all. This pass, run by the controller at start-up and
every hour, applies the rule to everything in /config/logs that it may delete:

1. **14 days:** a rotated s6-log file, or a Spytify log or events file, last written more than
   14 days ago is deleted.
2. **50 MB:** while the files it may delete pass 50 MB together, the oldest go: Spytify's events
   files first (the Logs tab doesn't show them, and a long item's can reach 150 MB), then the
   logs.

**Never deleted, and not counted in the 50 MB:** s6-log's `current` files (s6-log writes them),
the files of a run that's still going or that started after the runs were read (`protected`,
`newest_run`), rotated s6-log files last written since the oldest run still going started
(`keep_since_ns`: that run's controller, client and system lines), and any file whose name isn't
one of these patterns. They can't be deleted, so counting them would only take everything else:
a long item's events file alone can pass 50 MB.

**Times:** `now_ns` and `keep_since_ns` are compared with the files' last-write times, so they're
real time, never the fake world's clock.
"""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from spotivault.logview.files import S6_ROTATED, SPYTIFY_DIR, SPYTIFY_EVENTS, SPYTIFY_LOG
from spotivault.logview.lines import NS

log = logging.getLogger(__name__)

KEEP_DAYS = 14
BUDGET_BYTES = 50 * 1024 * 1024
DAY_NS = 86_400 * NS
_SERVICE = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: Path
    size: int
    mtime_ns: int
    events: bool  # a Spytify events file: deleted first when over the budget


@dataclass(frozen=True, slots=True)
class Pruned:
    deleted: int
    freed_bytes: int
    total_bytes: int  # what's left in /config/logs
    deletable_bytes: int  # what's left of the files the 50 MB applies to


def prune(
    logs_dir: Path,
    now_ns: int,
    *,
    protected: frozenset[int],
    newest_run: int,
    keep_since_ns: int | None = None,
    keep_days: int = KEEP_DAYS,
    budget_bytes: int = BUDGET_BYTES,
) -> Pruned:
    """Deletes what the rule says. `protected`: runs still going; `newest_run`: the highest run
    id when the runs were read (a run started since is protected too); `keep_since_ns`: when the
    oldest run still going started, or None."""
    total, candidates = _survey(logs_dir, protected, newest_run, keep_since_ns)
    deletable = sum(candidate.size for candidate in candidates)
    cutoff = now_ns - keep_days * DAY_NS
    deleted = 0
    freed = 0
    keep: list[_Candidate] = []
    for candidate in candidates:
        if candidate.mtime_ns < cutoff:
            if _delete(candidate):
                deleted += 1
                freed += candidate.size
                total -= candidate.size
                deletable -= candidate.size
        else:
            keep.append(candidate)
    # Over the budget: events files oldest first, then the logs oldest first.
    keep.sort(key=lambda c: (not c.events, c.mtime_ns))
    for candidate in keep:
        if deletable <= budget_bytes:
            break
        if _delete(candidate):
            deleted += 1
            freed += candidate.size
            total -= candidate.size
            deletable -= candidate.size
    if deleted:
        log.info(
            "logs: deleted %d old log files (%.1f MB); %.1f MB kept",
            deleted,
            freed / 1_048_576,
            total / 1_048_576,
        )
    return Pruned(deleted=deleted, freed_bytes=freed, total_bytes=total, deletable_bytes=deletable)


def _survey(
    logs_dir: Path, protected: frozenset[int], newest_run: int, keep_since_ns: int | None
) -> tuple[int, list[_Candidate]]:
    """The total size of /config/logs, and the files that may be deleted."""
    total = 0
    candidates: list[_Candidate] = []
    try:
        folders = [entry for entry in logs_dir.iterdir() if entry.is_dir()]
    except OSError:
        return 0, []
    for folder in folders:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            path = folder / name
            try:
                stat = path.stat()
            except OSError:
                continue
            if not os.path.isfile(path):
                continue
            total += stat.st_size
            if folder.name == SPYTIFY_DIR:
                log_match = SPYTIFY_LOG.fullmatch(name)
                events_match = SPYTIFY_EVENTS.fullmatch(name)
                match = log_match or events_match
                if match is None:
                    continue
                run = int(match["run"])
                if run in protected or run > newest_run:
                    continue  # its run is going, or started after the runs were read
                candidates.append(
                    _Candidate(path, stat.st_size, stat.st_mtime_ns, bool(events_match))
                )
            elif _SERVICE.fullmatch(folder.name) and S6_ROTATED.fullmatch(name):
                if keep_since_ns is not None and stat.st_mtime_ns >= keep_since_ns:
                    continue  # written during the run going: its lines
                candidates.append(_Candidate(path, stat.st_size, stat.st_mtime_ns, False))
    return total, candidates


def _delete(candidate: _Candidate) -> bool:
    try:
        candidate.path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("logs: couldn't delete %s: %s", candidate.path.name, exc)
        return False
    return True
