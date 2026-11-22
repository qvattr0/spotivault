"""One log line: how each format in /config/logs is read, its level, its place in the order, and
masking (History › Logs, web-ui.md § Logs tab; openapi.yaml `LogLine`).

The formats, as written in the container:

- **s6-log** (`<service>/current`, `@<tai64n>.s`): `2026-11-15 00:05:02.310000000  <text>`. The time
  is UTC: s6-log runs without TZ (svc-log isn't run with with-contenv).
- **The controller's text**, inside that: `INFO spotivault.catalog.library: …` (logs.FORMAT).
- **Spytify** (`spytify/<run>-<item>.log`): `2026-11-15T01:05:02.310000000+01:00 info  capture: …`,
  with the container's offset, made UTC here.

**Levels:** the controller's are Python's (CRITICAL is `error`); Spytify's are its own (`warn` is
`warning`). The other programs print no level, so only clear markers count: PulseAudio's `E:`
and `W:`, X's `(EE)` and `(WW)`, Chromium's `:ERROR:`, GLib's `-WARNING **`, a leading `Error:` or
`Warning:`. Anything else is `info`. A line that carries on the one before (a traceback's
indented lines; a line with no time) takes its level. So does a line whose time can't be one (a
month 13, a year before 1970): it's read as text, never as an error.

**Order:** a line's key is `(at_ns, service, dup)`. `dup` counts the lines before it in the same
file with the same time (s6-log's times are in nanoseconds, so it's nearly always 0). The key is
the line's `id` (`<at_ns>-<dup>-<service>`) and the paging cursor (`before`).

**Masking:** `logs.redact`, on every line that might hold a secret (`mask`). The controller's own
lines were masked when written; the client's and Spytify's weren't.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Literal

from spotivault.logs import redact

type Source = Literal["controller", "spytify", "client", "system"]
type Level = Literal["debug", "info", "warning", "error"]
type Key = tuple[int, str, int]  # (at_ns, service, dup)

SOURCES: tuple[Source, ...] = ("controller", "spytify", "client", "system")
LEVELS: tuple[Level, ...] = ("debug", "info", "warning", "error")
DEFAULT_LEVELS: frozenset[Level] = frozenset({"info", "warning", "error"})
MESSAGE_MAX = 4000  # LogLine.message's maxLength
NS = 1_000_000_000
# A line's time must lie between 1970 and the end of 9999 (a datetime's range), else it's text.
MAX_NS = (date(9999, 12, 31).toordinal() - date(1970, 1, 1).toordinal()) * 86_400 * NS

# s6-log's `T`: "YYYY-MM-DD HH:MM:SS.nnnnnnnnn" and two spaces.
_S6_LINE = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\.(\d{1,9}) {1,2}")
# Spytify's: Go's RFC3339Nano, its level padded to 5, then the message.
_SPYTIFY_LINE = re.compile(
    r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2}) ([a-zA-Z]+) ?"
)
# logs.FORMAT: "LEVEL logger: message".
_CONTROLLER_TEXT = re.compile(r"(DEBUG|INFO|WARNING|ERROR|CRITICAL) ([^\s:]+): ?")

_PYTHON_LEVELS: dict[str, Level] = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARNING": "warning",
    "ERROR": "error",
    "CRITICAL": "error",
}
_WORD_LEVELS: dict[str, Level] = {
    "debug": "debug",
    "trace": "debug",
    "verbose": "debug",
    "info": "info",
    "notice": "info",
    "warn": "warning",
    "warning": "warning",
    "error": "error",
    "err": "error",
    "fatal": "error",
    "critical": "error",
    "panic": "error",
    "e": "error",
    "w": "warning",
    "n": "info",
    "i": "info",
    "d": "debug",
    "ee": "error",
    "ww": "warning",
}
# Markers other programs print at the start of a line, for the client's and the system's lines.
_MARKER = re.compile(
    # Chromium (the client): [1121/183738.292224:ERROR:file.cc(12)] or [152:152:1121/…:WARNING:…]
    r"\[[\d:/.]+:(?P<chromium>INFO|WARNING|ERROR|FATAL|VERBOSE)\d*[:\]]"
    # PulseAudio: "E: [pulseaudio] …"
    r"|(?P<pulse>[EWNID]): \["
    # X: "(EE) …", "[    12.345] (WW) …"
    r"|(?:\[\s*[\d.]+\]\s*)?\((?P<x>EE|WW)\)"
    # A leading word and a colon: "Warning: …", "error: …"; "init: warning: …" is not one.
    r"|(?i:(?P<word>error|err|fatal|critical|panic|warning|warn|debug|info|notice))\s*:"
)
# GLib, anywhere in the line: "(spotify:152): Gtk-WARNING **: …"
_GLIB = re.compile(r"\b[A-Za-z]+-(WARNING|CRITICAL|ERROR) \*\*")

_EPOCH_ORDINAL = date(1970, 1, 1).toordinal()


@lru_cache(maxsize=4096)
def _second_ns(day: str, clock: str) -> int:
    """ "2026-11-15", "00:05:02" as nanoseconds since the epoch. Cached: lines share seconds.
    ValueError for a date that doesn't exist."""
    days = date(int(day[0:4]), int(day[5:7]), int(day[8:10])).toordinal() - _EPOCH_ORDINAL
    seconds = int(clock[0:2]) * 3600 + int(clock[3:5]) * 60 + int(clock[6:8])
    return (days * 86_400 + seconds) * NS


def _clock_ns(day: str, clock: str, fraction: str | None) -> int:
    nanos = int(fraction.ljust(9, "0")) if fraction else 0
    return _second_ns(day, clock) + nanos


def _time_ns(day: str, clock: str, fraction: str | None, offset: str = "Z") -> int | None:
    """A line's time in ns since the epoch, made UTC; None when it can't be a time (no such date,
    or outside 1970 to 9999)."""
    try:
        at_ns = _clock_ns(day, clock, fraction) - _offset_ns(offset)
    except ValueError:
        return None
    return at_ns if 0 <= at_ns <= MAX_NS else None


def _offset_ns(offset: str) -> int:
    if offset == "Z":
        return 0
    sign = -1 if offset[0] == "-" else 1
    return sign * (int(offset[1:3]) * 3600 + int(offset[4:6]) * 60) * NS


def iso_ms_ns(at_ns: int) -> str:
    """RFC 3339 UTC with milliseconds, as the API's times."""
    moment = datetime.fromtimestamp(at_ns // NS, UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + f".{(at_ns % NS) // 1_000_000:03d}Z"


def datetime_ns(moment: datetime) -> int:
    """An aware datetime as nanoseconds since the epoch (microsecond precision)."""
    delta = moment - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * NS + delta.microseconds * 1000


_ID = re.compile(r"(\d{1,20})-(\d{1,9})-([A-Za-z0-9_.-]{0,100})")


def encode_key(key: Key) -> str:
    """A key as a line's `id`, or a page's `next_before`."""
    at_ns, service, dup = key
    return f"{at_ns}-{dup}-{service}"


def decode_key(text: str) -> Key | None:
    """The key in an `id` or `before`, or None if it isn't one."""
    match = _ID.fullmatch(text)
    if match is None:
        return None
    return (int(match.group(1)), match.group(3), int(match.group(2)))


def mask(text: str, secrets: tuple[str, ...] = ()) -> str:
    """`text` through logs.redact, skipped when no pattern could match: each of logs._PATTERNS
    needs one of these words, or a bare token's AQ or BQ."""
    lowered = text.lower()
    if (
        "token" in lowered
        or "secret" in lowered
        or "verifier" in lowered
        or "password" in lowered
        or "bearer" in lowered
        or "basic" in lowered
        or "code=" in lowered
        or "AQ" in text
        or "BQ" in text
        or any(secret in text for secret in secrets if secret)
    ):
        return redact(text, secrets)
    return text


@dataclass(slots=True)
class Line:
    """One line of a log, as read. `text` is the message unmasked: `masked()` is what goes out."""

    at_ns: int
    service: str
    dup: int
    source: Source
    level: Level
    text: str
    run_id: int | None = None
    _masked: str | None = field(default=None, repr=False, compare=False)

    @property
    def key(self) -> Key:
        return (self.at_ns, self.service, self.dup)

    @property
    def id(self) -> str:
        return encode_key(self.key)

    def masked(self, secrets: tuple[str, ...] = ()) -> str:
        if self._masked is None:
            text = mask(self.text, secrets)
            if len(text) > MESSAGE_MAX:
                text = text[: MESSAGE_MAX - 1] + "…"
            self._masked = text
        return self._masked

    def to_api(self, secrets: tuple[str, ...] = ()) -> dict[str, object]:
        """The line as openapi.yaml's LogLine (and events.md's `log.lines`)."""
        return {
            "id": self.id,
            "at": iso_ms_ns(self.at_ns),
            "source": self.source,
            "service": self.service,
            "level": self.level,
            "message": self.masked(secrets),
            "run_id": self.run_id,
        }


def marker_level(text: str) -> Level | None:
    """The level a program's own marker gives a line, or None when it has none."""
    match = _MARKER.match(text)
    if match is not None:
        word = match.lastgroup and match.group(match.lastgroup)
        return _WORD_LEVELS.get((word or "").lower(), "info")
    if "**" in text:
        glib = _GLIB.search(text)
        if glib is not None:
            return _WORD_LEVELS.get(glib.group(1).lower(), "info")
    return None


class LineParser:
    """Reads one file's lines in order. It remembers the line before, for `dup` and for the lines
    that carry it on. `kind` is "s6" (s6-log's files) or "spytify"; `source` is the file's."""

    def __init__(
        self,
        *,
        kind: Literal["s6", "spytify"],
        source: Source,
        service: str,
        run_id: int | None = None,
        fallback_ns: int = 0,
    ) -> None:
        self.kind = kind
        self.source = source
        self.service = service
        self.run_id = run_id
        self.last_ns = fallback_ns  # a first line with no time sorts as the file's time
        self.dup = -1
        self.level: Level = "info"

    def parse(self, raw: str) -> Line:
        if self.kind == "spytify":
            at_ns, level, text = self._spytify(raw)
        else:
            at_ns, level, text = self._s6(raw)
        self.dup = self.dup + 1 if at_ns == self.last_ns else 0
        self.last_ns = at_ns
        self.level = level
        return Line(
            at_ns=at_ns,
            service=self.service,
            dup=self.dup,
            source=self.source,
            level=level,
            text=text,
            run_id=self.run_id,
        )

    def _s6(self, raw: str) -> tuple[int, Level, str]:
        match = _S6_LINE.match(raw)
        at_ns = None if match is None else _time_ns(match.group(1), match.group(2), match.group(3))
        if match is None or at_ns is None:
            return self.last_ns, self.level, raw  # no time: it carries on the line before
        rest = raw[match.end() :]
        if self.source == "controller":
            text_match = _CONTROLLER_TEXT.match(rest)
            if text_match is not None:
                return at_ns, _PYTHON_LEVELS[text_match.group(1)], rest[text_match.end() :]
            if rest[:1].isspace():
                return at_ns, self.level, rest  # a traceback's line
            return at_ns, "info", rest
        level = marker_level(rest)
        if level is None:
            level = self.level if rest[:1].isspace() and rest.strip() else "info"
        return at_ns, level, rest

    def _spytify(self, raw: str) -> tuple[int, Level, str]:
        match = _SPYTIFY_LINE.match(raw)
        if match is None:
            return self.last_ns, self.level, raw
        day, clock, fraction, offset, word = match.groups()
        at_ns = _time_ns(day, clock, fraction, offset)
        if at_ns is None:
            return self.last_ns, self.level, raw  # not a time after all: it carries on
        level = _WORD_LEVELS.get(word.lower())
        if level is None:  # not a level word: the message starts there
            return at_ns, "info", raw[match.start(5) :]
        return at_ns, level, raw[match.end() :].lstrip(" ")
