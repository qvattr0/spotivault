"""Smoke test helper: watches WS /api/events while the controller installs the client.

Runs inside the container, as app, with the controller's own Python (smoke.sh does this):

    docker exec -i -u app NAME /opt/spotivault/venv/bin/python -I - [TIMEOUT_S [PORT]] \
        < install_events.py

It connects as soon as the controller answers and reads the `hello`. If the controller hasn't
started an install by itself within a few seconds (the first start may), it starts one with
POST /api/client/install. Then it collects `client.install` events until the install ends, answers
the server's pings, and checks that `seq` has no gaps (contracts/events.md).

Prints one JSON summary line. Exits 0 when it saw install progress and the install finished.
Only the standard library and wsproto, which the controller's venv has.
"""

import http.client
import json
import socket
import sys
import time
from collections.abc import Iterator
from typing import Any

from wsproto import ConnectionType, WSConnection
from wsproto.events import (
    AcceptConnection,
    CloseConnection,
    Ping,
    RejectConnection,
    Request,
    TextMessage,
)

HOST = "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8080  # the controller's, inside the container
CONNECT_WITHIN_S = 120.0
SELF_START_AFTER_S = 5.0  # wait this long for an install the controller starts by itself


def connect(deadline: float) -> tuple[socket.socket, WSConnection]:
    """Opens WS /api/events, retrying until the controller answers or the deadline passes."""
    while True:
        try:
            sock = socket.create_connection((HOST, PORT), timeout=5)
            ws = WSConnection(ConnectionType.CLIENT)
            sock.sendall(ws.send(Request(host=f"{HOST}:{PORT}", target="/api/events")))
            while True:
                data = sock.recv(65536)
                if not data:
                    raise ConnectionError("closed during the handshake")
                ws.receive_data(data)
                for event in ws.events():
                    if isinstance(event, AcceptConnection):
                        sock.settimeout(1.0)
                        return sock, ws
                    if isinstance(event, RejectConnection):
                        raise ConnectionError(f"upgrade refused: HTTP {event.status_code}")
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def messages(sock: socket.socket, ws: WSConnection) -> Iterator[dict[str, Any] | None]:
    """Each event as a dict, or None once a second when nothing arrived. Answers pings."""
    parts: list[str] = []
    while True:
        try:
            data = sock.recv(65536)
        except TimeoutError:
            yield None
            continue
        if not data:
            return
        ws.receive_data(data)
        for event in ws.events():
            if isinstance(event, Ping):
                sock.sendall(ws.send(event.response()))
            elif isinstance(event, TextMessage):
                parts.append(event.data)
                if event.message_finished:
                    yield json.loads("".join(parts))
                    parts = []
            elif isinstance(event, CloseConnection):
                return


def start_install() -> tuple[int, str | None]:
    """POST /api/client/install: the status, and the error code if it was refused."""
    conn = http.client.HTTPConnection(HOST, PORT, timeout=10)
    try:
        conn.request("POST", "/api/client/install", body=b"", headers={"Content-Length": "0"})
        response = conn.getresponse()
        body = response.read()
    finally:
        conn.close()
    code = None
    if response.status >= 400:
        try:
            code = json.loads(body)["error"]["code"]
        except (ValueError, KeyError, TypeError):
            code = body[:200].decode(errors="replace")
    return response.status, code


def main() -> int:
    timeout_s = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
    t0 = time.monotonic()
    summary: dict[str, Any] = {
        "hello_install_state": None,
        "posted": None,
        "events": 0,
        "phases": [],
        "states": [],
        "download_events": 0,
        "max_progress": None,
        "seq_gaps": 0,
        "final_state": None,
        "version": None,
        "previous_version": None,
        "error": None,
        "log_tail": [],
        "connected_after_s": None,
        "elapsed_s": None,
    }
    try:
        sock, ws = connect(t0 + CONNECT_WITHIN_S)
    except OSError as exc:
        summary["error"] = f"can't connect to WS /api/events: {exc}"
        print(json.dumps(summary))
        return 1
    summary["connected_after_s"] = round(time.monotonic() - t0, 1)
    deadline = time.monotonic() + timeout_s
    self_start_by = time.monotonic() + SELF_START_AFTER_S
    started = False
    last_seq: int | None = None

    for message in messages(sock, ws):
        now = time.monotonic()
        if now > deadline:
            summary["error"] = summary["error"] or f"no end of the install within {timeout_s:.0f} s"
            break
        if message is None:
            if not started and summary["posted"] is None and now > self_start_by:
                status, code = start_install()
                summary["posted"] = status if code is None else f"{status} {code}"
                # 409 install_in_progress: the controller started one meanwhile. Events follow.
                if status != 202 and code != "install_in_progress":
                    summary["error"] = f"POST /api/client/install answered {status} {code}"
                    break
            continue

        seq = message.get("seq")
        if isinstance(seq, int):
            if last_seq is not None and seq != last_seq + 1:
                summary["seq_gaps"] += 1
            last_seq = seq
        if message.get("type") == "hello":
            install = message["data"]["client"]["install"]
            summary["hello_install_state"] = install["state"]
            started = install["state"] == "installing"
            continue
        if message.get("type") != "client.install":
            continue

        data = message["data"]
        started = True
        summary["events"] += 1
        if data["phase"] and data["phase"] not in summary["phases"]:
            summary["phases"].append(data["phase"])
        if data["state"] not in summary["states"]:
            summary["states"].append(data["state"])
        if data["phase"] == "download" and data["progress"] is not None:
            summary["download_events"] += 1
        if data["progress"] is not None:
            summary["max_progress"] = max(summary["max_progress"] or 0, data["progress"])
        if data["state"] in ("installed", "failed"):
            summary["final_state"] = data["state"]
            summary["version"] = data["version"]
            summary["previous_version"] = data["previous_version"]
            summary["error"] = data["error"]
            summary["log_tail"] = data["log_tail"][-3:]
            break
    else:
        summary["error"] = summary["error"] or "the server closed WS /api/events"

    sock.close()
    summary["elapsed_s"] = round(time.monotonic() - t0, 1)
    print(json.dumps(summary))
    ok = summary["final_state"] == "installed" and summary["events"] >= 2
    return 0 if ok and summary["seq_gaps"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
