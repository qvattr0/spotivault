"""Newline-delimited JSON-RPC 2.0 over spytifyd's Unix socket.

Owner: **recorder**. The wire rules are recorder/protocol.py's module docstring; probe.py's
`Spytify` class is the tested starting point, rewritten on asyncio streams:

- `asyncio.open_unix_connection(path, limit=protocol.MAX_LINE_BYTES + 1)`; never a blocking socket.
- One reader task per connection reads line after line, all the time: spytifyd drops a client
  512 lines behind. A line with an `id` and no `method` answers the pending request with that id;
  a line with a `method` and no `id` is a notification, put on an unbounded asyncio.Queue as a
  `ports.RecorderNotification` (received_at from the clock). Anything else is logged at debug and
  skipped. At EOF, every pending call gets RecorderGone and the queue ends.
- **The reader task** is the connection's own: `open()` starts it, it ends by itself at EOF (the
  socket closes when spytifyd exits), and `close()` cancels and awaits it. A failure in it is
  logged by a done-callback, so it's never lost.
- Requests: `{"jsonrpc": "2.0", "id": <int>, "method": ..., "params": {...}}` + "\n", ids 1, 2, 3 …
  per connection, written under an asyncio.Lock. An answer's `error` raises
  `ports.RecorderRpcError(method, code, message, data)`. No answer within `timeout_s` (raced
  against `clock.sleep`) raises TimeoutError; the late answer is then dropped.
- Never log params or results at info level: settings carry paths (fine) but nothing secret;
  still keep the log quiet.
"""

import asyncio
import json
import logging
import socket
import struct
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

from spotivault.ports import Clock, RecorderGone, RecorderNotification, RecorderRpcError
from spotivault.recorder import protocol as sp

log = logging.getLogger(__name__)


async def wait_on_clock[T](future: "asyncio.Future[T]", clock: Clock, timeout_s: float) -> T:
    """`future`'s result, or TimeoutError once `timeout_s` of `clock` time passed first.

    asyncio's own timeouts run on the loop's time; this one runs on services.clock, so a FakeClock
    test drives it. The future itself is never cancelled here: the caller decides what to do with
    it (a late JSON-RPC answer is dropped; a process keeps running).
    """
    if future.done():
        return future.result()
    timer = asyncio.ensure_future(clock.sleep(timeout_s))
    try:
        await asyncio.wait((future, timer), return_when=asyncio.FIRST_COMPLETED)
    finally:
        timer.cancel()  # nothing waits for it any more; a cancelled sleep is harmless
    if future.done():
        return future.result()
    raise TimeoutError(f"no result within {timeout_s} s")


class JsonRpcConnection:
    """One client connection to spytifyd's socket."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._next_id = 1
        # Requests sent and not answered yet: id → the future the reader resolves with the answer.
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._write_lock = asyncio.Lock()
        # Notifications in order; None marks the end (EOF or close()).
        self._queue: asyncio.Queue[RecorderNotification | None] = asyncio.Queue()
        self._closed = False

    @classmethod
    async def open(cls, path: Path, *, clock: Clock) -> "JsonRpcConnection":
        """Connects to the socket at `path` and starts reading. Raises OSError (such as
        FileNotFoundError or ConnectionRefusedError) when nothing listens there yet."""
        reader, writer = await asyncio.open_unix_connection(str(path), limit=sp.MAX_LINE_BYTES + 1)
        connection = cls(clock)
        connection._reader = reader
        connection._writer = writer
        connection._read_task = asyncio.create_task(
            connection._read_loop(), name=f"spytifyd socket {path.name}"
        )
        connection._read_task.add_done_callback(log_task_failure)
        return connection

    @property
    def closed(self) -> bool:
        """The socket reached EOF or was closed."""
        return self._closed

    @property
    def peer_pid(self) -> int | None:
        """The pid of the process listening on the other end (Linux SO_PEERCRED), or None when
        it can't be read. The recorder checks it's its own spytifyd, not one left running."""
        if self._writer is None:
            return None
        sock = self._writer.get_extra_info("socket")
        try:
            raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        except (AttributeError, OSError):  # not Linux, or the socket is gone
            return None
        pid, _uid, _gid = struct.unpack("3i", raw)
        return pid

    async def call(
        self, method: str, params: Mapping[str, Any] | None = None, *, timeout_s: float = 15.0
    ) -> Any:
        """Sends one request and returns its `result`. See the module docstring for errors."""
        if self._closed or self._writer is None:
            raise RecorderGone(f"{method}: the recorder's socket is closed")
        request_id = self._next_id
        self._next_id += 1
        answer: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = answer
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": dict(params) if params is not None else {},
        }
        line = json.dumps(request, separators=(",", ":"), ensure_ascii=False) + "\n"
        try:
            async with self._write_lock:
                self._writer.write(line.encode("utf-8"))
                await self._writer.drain()
            message = await wait_on_clock(answer, self.clock, timeout_s)
        except TimeoutError:
            log.warning("spytifyd: %s got no answer within %.0f s", method, timeout_s)
            raise TimeoutError(f"{method}: no answer within {timeout_s} s") from None
        except (ConnectionError, OSError) as exc:  # the socket broke while writing
            raise RecorderGone(f"{method}: the recorder's socket is closed ({exc})") from exc
        finally:
            # A late answer finds no one waiting and is dropped by the reader.
            self._pending.pop(request_id, None)
            if not answer.done():
                answer.cancel()
            elif not answer.cancelled():
                answer.exception()  # marks a RecorderGone nobody else reads as seen (no warning)
        error = message.get("error")
        if error is not None:
            raise _rpc_error(method, error)
        return message.get("result")

    async def notifications(self) -> AsyncIterator[RecorderNotification]:
        """The notifications, in order, until EOF. One consumer."""
        while True:
            notification = await self._queue.get()
            if notification is None:
                self._queue.put_nowait(None)  # a second iteration ends at once too
                return
            yield notification

    async def close(self) -> None:
        """Closes the socket and stops the reader. Safe to call twice."""
        task = self._read_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._finish()

    # --- The reader ------------------------------------------------------------------------------

    async def _read_loop(self) -> None:
        """Reads every line until EOF, then fails the waiting calls and ends the queue."""
        assert self._reader is not None
        try:
            while True:
                try:
                    line = await self._reader.readline()
                except ValueError:
                    # Longer than MAX_LINE_BYTES: spytifyd never sends one. asyncio dropped what it
                    # had buffered; the rest of that line comes next and fails to parse.
                    log.debug("spytifyd: skipped a line over %d bytes", sp.MAX_LINE_BYTES)
                    continue
                except ConnectionError:
                    break
                if not line:
                    break  # EOF: spytifyd closed the socket (it exits) or dropped us
                self._handle_line(line)
        finally:
            self._finish()

    def _handle_line(self, line: bytes) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            log.debug("spytifyd: skipped a line that isn't JSON: %r", line[:200])
            return
        if not isinstance(message, dict):
            log.debug("spytifyd: skipped a line that isn't a JSON object")
            return
        method = message.get("method")
        message_id = message.get("id")
        if isinstance(method, str) and message_id is None:
            params = message.get("params")
            self._queue.put_nowait(
                RecorderNotification(
                    method=method,
                    params=params if isinstance(params, dict) else {},
                    received_at=self.clock.now(),
                )
            )
            return
        if method is None and isinstance(message_id, int) and not isinstance(message_id, bool):
            answer = self._pending.get(message_id)
            if answer is None or answer.done():
                # A late answer after a timeout, or id 0: spytifyd's reply to a line it couldn't
                # parse (never ours: ids start at 1).
                log.debug("spytifyd: an answer to request %d, which nothing waits for", message_id)
                return
            answer.set_result(message)
            return
        log.debug("spytifyd: skipped a message that's neither an answer nor a notification")

    def _finish(self) -> None:
        """The connection is over: fail what waits, end the notifications, free the socket."""
        if self._closed:
            return
        self._closed = True
        for answer in self._pending.values():
            if not answer.done():
                answer.set_exception(RecorderGone("the recorder's socket closed"))
        self._pending.clear()
        self._queue.put_nowait(None)
        if self._writer is not None:
            self._writer.close()


def _rpc_error(method: str, error: Any) -> RecorderRpcError:
    """The RecorderRpcError for an answer's `error` object (`{code, message, data?}`)."""
    if not isinstance(error, dict):
        return RecorderRpcError(method, sp.INTERNAL_ERROR, str(error))
    code = error.get("code")
    message = error.get("message")
    return RecorderRpcError(
        method,
        code if isinstance(code, int) and not isinstance(code, bool) else sp.INTERNAL_ERROR,
        message if isinstance(message, str) else "",
        error.get("data"),
    )


def log_task_failure(task: "asyncio.Task[Any]") -> None:
    """A done-callback: logs a task's unexpected exception, so it's never lost."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("spytifyd: %s failed", task.get_name(), exc_info=exc)
