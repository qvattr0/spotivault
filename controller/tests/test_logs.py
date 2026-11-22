"""logs.py: the line format, redaction, the writer thread and the loop-lag throttle."""

import contextlib
import io
import logging
import queue
import signal
import sys
import threading
import warnings
from collections.abc import Iterator

import pytest

from spotivault import logs
from spotivault.config import Config, load_config
from spotivault.loopwatch import LoopWatch


@contextlib.contextmanager
def logging_to_string(config: Config) -> Iterator[io.StringIO]:
    """logs.configure() writing to a string; on exit, waits for the writer thread and puts the
    logging setup back. Used inside a test, so pytest's own capture handlers come back as they
    were."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    quiet = {name: logging.getLogger(name).level for name in logs.QUIET_LOGGERS}
    stream = io.StringIO()
    logs.configure(config, stream=stream)
    try:
        yield stream
    finally:
        logs.shutdown()
        root.handlers[:] = handlers
        root.setLevel(level)
        for name, quiet_level in quiet.items():
            logging.getLogger(name).setLevel(quiet_level)


def lines_of(stream: io.StringIO, *, without_time: bool = False) -> list[str]:
    lines = stream.getvalue().splitlines()
    return [line.split(" ", 1)[1] for line in lines] if without_time else lines


def test_one_line_per_record(env: dict[str, str]) -> None:
    real = load_config({**env, "SPOTIVAULT_FAKE": "0"})
    with logging_to_string(real) as stream:
        logging.getLogger("spotivault.test").info("hello %s", "world")
        logging.getLogger("spotivault.test").debug("not at INFO")
    assert lines_of(stream) == ["INFO spotivault.test: hello world"]


def test_fake_mode_adds_the_time(config: Config) -> None:
    assert config.fake
    with logging_to_string(config) as stream:
        logging.getLogger("spotivault.test").warning("careful")
    (line,) = lines_of(stream)
    time, rest = line.split(" ", 1)
    assert len(time) == len("12:34:56.789")
    assert rest == "WARNING spotivault.test: careful"


def test_extra_lines_are_indented(config: Config) -> None:
    log = logging.getLogger("spotivault.test")
    with logging_to_string(config) as stream:
        log.error("two\nlines\r\nERROR fake.logger: not a record")
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("it failed")
    lines = lines_of(stream)
    starts = [line for line in lines if not line.startswith(logs.CONTINUATION)]
    assert len(starts) == 2  # two records, however many lines
    assert lines[1] == logs.CONTINUATION + "lines"
    assert lines[2] == logs.CONTINUATION + "ERROR fake.logger: not a record"
    assert "it failed" in lines[3]
    assert lines[-1] == logs.CONTINUATION + "ValueError: boom"


def test_secrets_never_reach_the_log(env: dict[str, str]) -> None:
    config = load_config({**env, "UI_PASSWORD": "hunter2-hunter2"})
    log = logging.getLogger("spotivault.test")
    token = "BQ" + "x" * 150
    with logging_to_string(config) as stream:
        log.info("token %s", {"access_token": token, "expires_in": 3600})
        log.info('{"refresh_token":"AQshort","scope":"user-library-read"}')
        log.info("POST body code_verifier=abc123def&client_id=0123456789abcdef")
        log.info("headers: Authorization: Bearer %s", token)
        log.info("callback http://127.0.0.1:8888/callback?code=AQB3xyz&state=k7Qm2c")
        log.info("the password is %s", "hunter2-hunter2")
        try:
            raise RuntimeError(f"refused: {token}")
        except RuntimeError:
            log.exception("failed")
    text = stream.getvalue()
    for secret in (token, "AQshort", "abc123def", "AQB3xyz", "hunter2-hunter2"):
        assert secret not in text
    assert "client_id=0123456789abcdef" in text  # not a secret
    assert "state=k7Qm2c" in text
    assert "user-library-read" in text
    assert "'expires_in': 3600" in text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("'access_token': 'BQabc'", f"'access_token': '{logs.REDACTED}'"),
        ('"refresh_token": "AQabc"', f'"refresh_token": "{logs.REDACTED}"'),
        ("UI_PASSWORD=secret", f"UI_PASSWORD={logs.REDACTED}"),
        ("Authorization: Bearer abcdefgh123", f"Authorization: Bearer {logs.REDACTED}"),
        ("Authorization: Basic dXNlcjpwYXNz", f"Authorization: Basic {logs.REDACTED}"),
        ("/callback?code=AQx&state=s", f"/callback?code={logs.REDACTED}&state=s"),
        # Ordinary words and codes are kept.
        ('{"code": "not_connected"}', '{"code": "not_connected"}'),
        ("closed with code=1013", "closed with code=1013"),
        ("PUT /me/player/repeat?state=context", "PUT /me/player/repeat?state=context"),
        ("UI_PASSWORD is set but not enforced in M1", "UI_PASSWORD is set but not enforced in M1"),
        ("the password is wrong", "the password is wrong"),
        ("playlist 3cEYpjA9oz9GiPac4AsH4n", "playlist 3cEYpjA9oz9GiPac4AsH4n"),
    ],
)
def test_redact(text: str, expected: str) -> None:
    assert logs.redact(text) == expected


def test_a_short_ui_password_is_not_masked_as_a_word() -> None:
    assert logs.redact("app started", secrets=["app"]) == "app started"
    assert logs.redact("pw sesame1 here", secrets=["sesame1"]) == f"pw {logs.REDACTED} here"


def test_uvicorn_and_httpx(config: Config) -> None:
    with logging_to_string(config) as stream:
        logging.getLogger("uvicorn.error").info("Started server process")
        logging.getLogger("httpx").info('HTTP Request: GET https://api.spotify.com/v1/me "200 OK"')
        logging.getLogger("httpx").warning("a warning still shows")
    assert lines_of(stream, without_time=True) == [
        "INFO uvicorn.error: Started server process",
        "WARNING httpx: a warning still shows",
    ]


def test_loop_lag_warnings_are_throttled(config: Config) -> None:
    log = logging.getLogger(logs.LOOPWATCH_LOGGER)
    now = [1000.0]
    with logging_to_string(config) as stream:
        throttle = logs._lag_throttle
        assert throttle is not None
        throttle.now = lambda: now[0]
        log.warning("the event loop ran %.0f ms late", 300)
        for _ in range(5):
            now[0] += 0.5
            log.warning("the event loop ran %.0f ms late", 400)
        now[0] += logs.LAG_WARNING_EVERY_S
        log.warning("the event loop ran %.0f ms late", 500)
    assert lines_of(stream, without_time=True) == [
        "WARNING spotivault.loopwatch: the event loop ran 300 ms late",
        "WARNING spotivault.loopwatch: the event loop ran 500 ms late "
        "(and 5 more since the last warning)",
    ]


def test_loopwatch_warnings_reach_the_log(config: Config) -> None:
    with logging_to_string(config) as stream:
        LoopWatch().record(0.3)
    (line,) = lines_of(stream)
    assert "WARNING spotivault.loopwatch: the event loop ran 300 ms late" in line


def test_a_full_queue_drops_and_counts() -> None:
    records: queue.Queue[logging.LogRecord | None] = queue.Queue(2)
    handler = logs.DroppingQueueHandler(records)
    log = logging.getLogger("spotivault.test.dropping")
    for n in range(5):
        handler.handle(log.makeRecord(log.name, logging.INFO, __file__, 1, f"n={n}", None, None))
    assert handler.dropped == 3
    taken = [records.get_nowait(), records.get_nowait()]
    assert [r.getMessage() for r in taken if r] == ["n=0", "n=1"]
    handler.handle(log.makeRecord(log.name, logging.INFO, __file__, 1, "n=5", None, None))
    note, latest = records.get_nowait(), records.get_nowait()
    assert note is not None and latest is not None
    assert note.getMessage() == "3 log records dropped: the log output was blocked"
    assert latest.getMessage() == "n=5"
    assert handler.dropped == 0


def test_configure_twice_keeps_one_handler(config: Config) -> None:
    with logging_to_string(config) as first, logging_to_string(config) as second:
        root = logging.getLogger()
        assert len([h for h in root.handlers if isinstance(h, logs.DroppingQueueHandler)]) == 1
        logging.getLogger("spotivault.test").info("once")
    assert lines_of(first) == []
    assert len(lines_of(second)) == 1


def test_uncaught_exceptions_are_logged_and_redacted(config: Config) -> None:
    token = "AQ" + "y" * 120
    with logging_to_string(config) as stream:
        try:
            raise RuntimeError(f"exchange failed for {token}")
        except RuntimeError as exc:
            sys.excepthook(type(exc), exc, exc.__traceback__)
        thread = threading.Thread(target=_fails_with, args=(token,), name="worker")
        thread.start()
        thread.join()
    assert sys.excepthook is sys.__excepthook__  # put back
    text = stream.getvalue()
    assert "CRITICAL spotivault: uncaught exception" in text
    assert "ERROR spotivault: uncaught exception in worker" in text
    assert token not in text
    assert text.count("RuntimeError: exchange failed for [redacted]") == 2


def _fails_with(token: str) -> None:
    raise RuntimeError(f"exchange failed for {token}")


def test_warnings_go_to_the_log(config: Config) -> None:
    with logging_to_string(config) as stream:
        warnings.warn("something old", UserWarning, stacklevel=1)
    assert "WARNING py.warnings:" in stream.getvalue()
    assert "something old" in stream.getvalue()


def test_sigterm_exits_normally_so_the_log_is_written(config: Config) -> None:
    before = signal.getsignal(signal.SIGTERM)
    with logging_to_string(config) as stream:
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler) and handler is not before
        logging.getLogger("spotivault.test").info("the last line")
        with pytest.raises(SystemExit) as exited:
            handler(signal.SIGTERM, None)
        assert exited.value.code == 0
    assert signal.getsignal(signal.SIGTERM) is before  # put back
    assert "the last line" in stream.getvalue()
