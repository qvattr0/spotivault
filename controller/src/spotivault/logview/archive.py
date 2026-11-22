"""GET /api/logs/download: the logs as a .zip, for bug reports (web-ui.md § Logs tab). Blocking:
build it in a thread.

Every log file `files.list_files` shows (s6-log's `current` and rotated files, Spytify's item logs,
never its events files) that was written to in the last `days` days goes in whole, under its
folder's name. Every line is masked on the way in (`lines.mask`), as the Logs tab shows it: the
client's and Spytify's own output was never masked when written.
"""

import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from spotivault.logview.files import list_files
from spotivault.logview.lines import NS, mask

SPOOL_BYTES = 4 * 1024 * 1024  # the zip stays in memory up to this, then goes to a temporary file
CHUNK = 64 * 1024


def build_zip(logs_dir: Path, since_ns: int, secrets: tuple[str, ...] = ()) -> IO[bytes]:
    """The zip, in a spooled temporary file at its start. The caller closes it."""
    out = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)  # the caller closes it
    try:
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for file in list_files(logs_dir):
                try:
                    stat = file.path.stat()
                except OSError:
                    continue
                if stat.st_mtime_ns < since_ns:
                    continue
                info = zipfile.ZipInfo(file.archive_name, _zip_time(stat.st_mtime_ns))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                try:
                    with file.path.open("rb") as source, zf.open(info, "w") as dest:
                        for raw in source:
                            text = raw.decode("utf-8", errors="replace")
                            dest.write(mask(text, secrets).encode("utf-8"))
                except OSError:
                    continue  # deleted while it was read
        out.seek(0)
    except BaseException:
        out.close()
        raise
    return out


def _zip_time(mtime_ns: int) -> tuple[int, int, int, int, int, int]:
    moment = datetime.fromtimestamp(mtime_ns // NS, UTC)
    return (
        max(moment.year, 1980),
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
    )


def read_chunk(handle: IO[bytes]) -> bytes:
    return handle.read(CHUNK)
