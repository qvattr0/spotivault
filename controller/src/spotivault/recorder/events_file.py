"""Reading spytifyd's `--events` file: every notification it sent, one JSON object per line.

Owner: **recorder**. spytifyd appends `{"method": "<event>", "params": {...}}` per line (Go's
`proto.Event`, no `jsonrpc` key), level and log events included, from the moment its socket is
up until it exits. S0 found it holds the last `track.finished`, written as the process exits
(FINDINGS row 27). The item engine compares it with what the socket delivered and takes any take
the socket lost (design.md § Run flow step 6, "Read every event").

- A line that isn't a JSON object with a string `method` is skipped (a crash can cut the last
  line short). `params` that isn't an object (Go writes `null` for none) is read as `{}`.
- **`level` records are left out.** spytifyd sends one up to 10 times a second while it records,
  so a long item's file holds hundreds of thousands; they're only the meter, and keeping them
  would fill memory. They're dropped before the JSON is parsed (Go writes `{"method":"level",`).
- Blocking file work: `load_events_file` runs `read_events_file` with asyncio.to_thread.
- `received_at` is the time of reading (the file has no times): the clock's now, for every record.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from spotivault.ports import Clock, RecorderNotification

log = logging.getLogger(__name__)

LEFT_OUT = frozenset({"level"})  # see the module docstring
_LEVEL_PREFIX = b'{"method":"level"'


def read_events_file(path: Path, *, received_at: datetime) -> list[RecorderNotification]:
    """The file's records, in order. A missing file is an empty list. Blocking."""
    records: list[RecorderNotification] = []
    skipped = 0
    try:
        with path.open("rb") as file:
            for line in file:
                if line.startswith(_LEVEL_PREFIX):
                    continue  # the meter: left out unparsed (module docstring)
                record = _parse_line(line, received_at)
                if record is None:
                    if line.strip():
                        skipped += 1
                    continue
                records.append(record)
    except FileNotFoundError:
        return []
    if skipped:
        log.info("spytifyd events file %s: skipped %d unreadable lines", path.name, skipped)
    return records


async def load_events_file(path: Path, clock: Clock) -> list[RecorderNotification]:
    """`read_events_file` on a worker thread, `received_at` = clock.now()."""
    return await asyncio.to_thread(read_events_file, path, received_at=clock.now())


def _parse_line(line: bytes, received_at: datetime) -> RecorderNotification | None:
    """One line as a notification, or None for a line to skip."""
    try:
        record = json.loads(line)
    except ValueError:  # cut short, or not UTF-8 / JSON
        return None
    if not isinstance(record, dict):
        return None
    method = record.get("method")
    if not isinstance(method, str) or not method:
        return None
    if method in LEFT_OUT:
        return None
    params = record.get("params")
    return RecorderNotification(
        method=method,
        params=params if isinstance(params, dict) else {},
        received_at=received_at,
    )
