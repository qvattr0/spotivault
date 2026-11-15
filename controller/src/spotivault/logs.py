"""Logging for the controller: one record per line on stdout, for s6-log.

In the container, s6's `controller-log` service reads the controller's stdout. It prefixes each
line with `controller:` on docker's output, and writes it with a timestamp to
/config/logs/controller/current (10 files of 1 MB). So a line here is just
`LEVEL logger: message`, with no time of its own. Fake mode runs in a terminal, so it adds the time.
History's Logs tab, `log.line` events and the logs zip are deferred past M1 (plan § Scope).

    logs.configure(config)        # once, by `python -m spotivault`, before anything logs

What it takes care of:
- **Never blocks the event loop.** Records go through a bounded queue to a writer thread. s6-log
  runs with `-b`: when /config is slow or full, it stops reading, the pipe fills, and a direct
  write would freeze the whole controller. When the queue is full, records are dropped and
  counted, and the count is logged once the queue has room again.
- **Never logs a secret.** `redact()` masks Spotify tokens, the auth code in a callback address,
  PKCE verifiers, `Authorization` values and the UI password, in every line, tracebacks included.
  Code should still never log them on purpose: this is the safety net.
- **One record, one block.** A message's extra lines (a traceback) are indented, so a line that
  starts at the margin always starts a record, and a message can't pass itself off as another.
- **Loop lag.** loopwatch warns whenever the event loop runs over 250 ms late. If something keeps
  blocking it, that's twice a second: LagThrottle lets one through every LAG_WARNING_EVERY_S, with
  a count of the ones held back.
- **Quiet libraries.** httpx and httpcore log every request at INFO; they're held at WARNING (S5
  keeps its own Web API usage log).
- **Nothing around it.** Python's warnings and uncaught exceptions (in the main thread or another)
  go through the log too, so they're redacted like the rest.
- **The last lines on SIGTERM.** While it serves, uvicorn handles SIGTERM itself (a graceful
  shutdown, up to 30 s), then raises the signal again for the handler it found. The default one
  would kill the process with the last lines still queued, so `configure()` installs one that
  exits normally instead (status 0, a clean stop): the exit writes what's queued.
"""

import atexit
import logging
import logging.handlers
import queue
import re
import signal
import sys
import threading
import time
from collections.abc import Callable, Sequence
from types import FrameType, TracebackType
from typing import Any, TextIO

from spotivault.config import Config

FORMAT = "%(levelname)s %(name)s: %(message)s"
FAKE_FORMAT = "%(asctime)s.%(msecs)03d " + FORMAT
FAKE_DATE_FORMAT = "%H:%M:%S"

QUEUE_SIZE = 10_000  # records waiting for the writer thread before new ones are dropped
FLUSH_TIMEOUT_S = 5.0  # at exit, how long the writer may take to write what's queued
LAG_WARNING_EVERY_S = 10.0
QUIET_LOGGERS = ("httpx", "httpcore")
LOOPWATCH_LOGGER = "spotivault.loopwatch"
CONTINUATION = "    "  # the indent of a record's extra lines

REDACTED = "[redacted]"
_SECRET_KEYS = (
    "access_token|refresh_token|id_token|client_secret|code_verifier|password|ui_password"
)
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # "access_token": "…", access_token=…, 'code_verifier': '…' (JSON, a dict, a form or a URL)
    (
        re.compile(rf"""(?i)(["']?\b(?:{_SECRET_KEYS})\b["']?\s*[:=]\s*["']?)[^"'\s&,;}}]+"""),
        rf"\g<1>{REDACTED}",
    ),
    # Authorization: Bearer … / Basic …
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), rf"\g<1> {REDACTED}"),
    # The auth code in a callback address: http://127.0.0.1:8888/callback?code=…&state=…
    (re.compile(r"(?i)([?&]code=)[^&\s\"'#]+"), rf"\g<1>{REDACTED}"),
    # A bare Spotify token or auth code: access tokens start with BQ, codes and refresh tokens AQ.
    (re.compile(r"\b[AB]Q[A-Za-z0-9_-]{40,}"), REDACTED),
]
MIN_SECRET_LENGTH = 4  # a shorter UI password isn't masked as a literal: it would mask every word

_writer: "LogWriter | None" = None
_lag_throttle: "LagThrottle | None" = None
_previous_sigterm: Any = None  # the SIGTERM handler configure() replaced; shutdown() restores it


def configure(config: Config, *, stream: TextIO | None = None) -> None:
    """Sends every logger's records to stdout (or `stream`) at config.log_level, through the
    writer thread. Calling it again replaces the previous setup."""
    global _writer, _lag_throttle
    shutdown()

    secrets = [config.ui_password] if config.ui_password else []
    output = logging.StreamHandler(stream or sys.stdout)
    output.setFormatter(
        LineFormatter(
            FAKE_FORMAT if config.fake else FORMAT,
            datefmt=FAKE_DATE_FORMAT if config.fake else None,
            secrets=secrets,
        )
    )
    records: queue.Queue[logging.LogRecord | None] = queue.Queue(QUEUE_SIZE)
    _writer = LogWriter(records, output)
    _writer.start()

    root = logging.getLogger()
    root.handlers[:] = [DroppingQueueHandler(records)]
    root.setLevel(config.log_level)
    # uvicorn's own loggers go through the root logger too (log_config=None in __main__).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    _lag_throttle = LagThrottle()
    logging.getLogger(LOOPWATCH_LOGGER).addFilter(_lag_throttle)
    logging.captureWarnings(True)
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_uncaught_in_thread
    _set_sigterm_handler(_exit_on_sigterm)


def shutdown() -> None:
    """Writes what's queued (for up to FLUSH_TIMEOUT_S) and stops the writer thread. Runs at exit;
    safe to call more than once."""
    global _writer, _lag_throttle
    _set_sigterm_handler(None)
    if _lag_throttle is not None:
        logging.getLogger(LOOPWATCH_LOGGER).removeFilter(_lag_throttle)
        _lag_throttle = None
    if _writer is not None:
        root = logging.getLogger()
        root.handlers[:] = [h for h in root.handlers if not isinstance(h, DroppingQueueHandler)]
        _writer.stop(FLUSH_TIMEOUT_S)
        _writer = None
        logging.captureWarnings(False)
        sys.excepthook = sys.__excepthook__
        threading.excepthook = threading.__excepthook__


atexit.register(shutdown)


def _exit_on_sigterm(signum: int, frame: FrameType | None) -> None:
    """SIGTERM when uvicorn isn't handling it: before it serves, or raised again by uvicorn after
    its graceful shutdown. A normal exit, so atexit writes what the log still holds."""
    raise SystemExit(0)


def _set_sigterm_handler(handler: Callable[[int, FrameType | None], None] | None) -> None:
    """Installs `handler` for SIGTERM, or (None) puts back the one it replaced. Signal handlers
    can only be set from the main thread; elsewhere this does nothing."""
    global _previous_sigterm
    if threading.current_thread() is not threading.main_thread():
        return
    if handler is not None:
        previous = signal.signal(signal.SIGTERM, handler)
        if _previous_sigterm is None:
            _previous_sigterm = previous
    elif _previous_sigterm is not None:
        signal.signal(signal.SIGTERM, _previous_sigterm)
        _previous_sigterm = None


def _log_uncaught(
    kind: type[BaseException], exc: BaseException, traceback: TracebackType | None
) -> None:
    if issubclass(kind, KeyboardInterrupt):
        sys.__excepthook__(kind, exc, traceback)
        return
    logging.getLogger("spotivault").critical("uncaught exception", exc_info=(kind, exc, traceback))


def _log_uncaught_in_thread(args: threading.ExceptHookArgs) -> None:
    if args.exc_value is None:
        return
    name = args.thread.name if args.thread is not None else "a thread"
    logging.getLogger("spotivault").error(
        "uncaught exception in %s",
        name,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def redact(text: str, secrets: Sequence[str] = ()) -> str:
    """`text` with every secret masked: the patterns above, and each literal in `secrets`."""
    for secret in secrets:
        if len(secret) >= MIN_SECRET_LENGTH:
            text = text.replace(secret, REDACTED)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class LineFormatter(logging.Formatter):
    """The standard format, then redacted, with a record's extra lines indented."""

    def __init__(
        self, fmt: str, datefmt: str | None = None, *, secrets: Sequence[str] = ()
    ) -> None:
        super().__init__(fmt, datefmt)
        self.secrets = list(secrets)

    def format(self, record: logging.LogRecord) -> str:
        text = redact(super().format(record), self.secrets)
        lines = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n").split("\n")
        return ("\n" + CONTINUATION).join(lines)


class DroppingQueueHandler(logging.handlers.QueueHandler):
    """Puts records on the writer's queue, never waiting: when it's full, a record is dropped and
    counted, and the count goes out as a warning once there's room again."""

    def __init__(self, records: "queue.Queue[logging.LogRecord | None]") -> None:
        super().__init__(records)
        self.dropped = 0

    def enqueue(self, record: logging.LogRecord) -> None:
        # Handler.handle() holds the handler's lock here, so threads don't race on `dropped`.
        try:
            if self.dropped:
                self.queue.put_nowait(self._dropped_note())
                self.dropped = 0
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped += 1

    def _dropped_note(self) -> logging.LogRecord:
        return logging.makeLogRecord(
            {
                "name": __name__,
                "levelno": logging.WARNING,
                "levelname": "WARNING",
                "msg": f"{self.dropped} log records dropped: the log output was blocked",
            }
        )


class LogWriter:
    """The thread that writes queued records to the output handler. `None` on the queue stops it."""

    def __init__(
        self, records: "queue.Queue[logging.LogRecord | None]", output: logging.Handler
    ) -> None:
        self.records = records
        self.output = output
        self._thread = threading.Thread(target=self._run, name="log-writer", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout_s: float) -> None:
        """Asks the thread to finish what's queued, and waits for it, up to `timeout_s`."""
        try:
            self.records.put(None, timeout=timeout_s)
        except queue.Full:
            return  # the output is stuck: give up, the thread is a daemon
        self._thread.join(timeout_s)

    def _run(self) -> None:
        while True:
            record = self.records.get()
            if record is None:
                return
            self.output.handle(record)


class LagThrottle(logging.Filter):
    """Lets one loopwatch warning through every `every_s` seconds. The ones held back are counted,
    and the next warning that goes out says how many there were."""

    def __init__(
        self, every_s: float = LAG_WARNING_EVERY_S, now: Callable[[], float] = time.monotonic
    ) -> None:
        super().__init__()
        self.every_s = every_s
        self.now = now
        self.held = 0
        self._last: float | None = None

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING:
            return True
        now = self.now()
        if self._last is not None and now - self._last < self.every_s:
            self.held += 1
            return False
        if self.held:
            record.msg = f"{record.getMessage()} (and {self.held} more since the last warning)"
            record.args = None
            self.held = 0
        self._last = now
        return True
