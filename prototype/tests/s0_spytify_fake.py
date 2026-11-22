#!/usr/bin/env python3
"""S0 (M1 plan): spytifyd checks with its built-in fake player, no Spotify needed.

- Does the `--events FILE` stream contain the last take's `track.finished` (written as the
  process exits after the idle exit)?
- Is `settings.set` over the socket persisted to $SPYTIFY_CONFIG, and `--set` not?
- Which files does the naming layout give (`output.group_by=artist/album`,
  `output.template={track} - {title}`)?
- How long after the pause does `--idle-exit` end the process?

Run inside the prototype container as `app`:
    docker exec -u app spotivault-prototype python3 /config/s0/s0_spytify_fake.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

W = tempfile.mkdtemp(prefix="s0sp.")
TIMELINE = {
    "name": "two tracks, then paused at the end",
    "seed": 1, "lead_in_ms": 300, "tail_ms": 0,
    "items": [
        {"artist": "Artist", "title": "One", "album": "Album", "track_number": 1, "length_ms": 4000, "art": "none"},
        {"artist": "Artist", "title": "Two", "album": "Album", "track_number": 2, "length_ms": 4000, "art": "none",
         "gap_ms": 300},
        # Track 1 loaded again and paused at its start, as Spotify does at the end of an album.
        {"artist": "Artist", "title": "One", "album": "Album", "track_number": 1, "length_ms": 4000, "art": "none",
         "pause_at_ms": 1, "pause_ms": 60000, "desync_ms": 120000},
    ],
}


def rpc(path, method, params=None, rid=1):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(path)
    s.sendall((json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}) + "\n").encode())
    f = s.makefile("rb")
    for line in f:
        msg = json.loads(line)
        if msg.get("id") == rid:
            s.close()
            return msg
    return None


def main():
    tl = os.path.join(W, "timeline.json")
    with open(tl, "w") as f:
        json.dump(TIMELINE, f)
    cfg = os.path.join(W, "cfg", "config.toml")
    sock = os.path.join(W, "run", "spytify.sock")
    env = dict(os.environ, SPYTIFY_CONFIG=cfg, SPYTIFY_SOCKET=sock)
    out = os.path.join(W, "out")
    cmd = ["spytifyd", "--once", "--serve", "--idle-exit", "3s", "--fake", tl, "--fake-realtime",
           "--events", os.path.join(W, "events.jsonl"), "--log-file", os.path.join(W, "spytifyd.log"),
           "--set", f"output.dir={out}", "--set", "encode.format=aac", "--set", "encode.bitrate_kbps=256",
           "--set", "output.group_by=artist/album", "--set", "output.template={track} - {title}",
           "--set", "output.prefix=none", "--set", "recorder.duplicates=skip",
           "--set", "recorder.skip_duplicates_forward=false"]
    t0 = time.time()
    proc = subprocess.Popen(cmd, env=env, cwd=W, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(40):
        if os.path.exists(sock):
            break
        time.sleep(0.25)
    info = rpc(sock, "core.info")
    print("version:", (info or {}).get("result", {}).get("version"))
    print("warnings:", (info or {}).get("result", {}).get("warnings"))
    res = rpc(sock, "settings.set", {"values": {"recorder.silence_db": -55}}, rid=2)
    print("settings.set ->", (res or {}).get("result"))
    code = proc.wait(timeout=120)
    print(f"exit code {code} after {time.time() - t0:.1f}s")

    events = [json.loads(l) for l in open(os.path.join(W, "events.jsonl"))]
    seq = [(e["method"], (e.get("params") or {}).get("title") or (e.get("params") or {}).get("reason")
            or os.path.basename((e.get("params") or {}).get("path") or "") or (e.get("params") or {}).get("state"))
           for e in events if e["method"] not in ("level", "log")]
    print("events:", json.dumps(seq))
    finished = [e for e in events if e["method"] == "track.finished"]
    print("track.finished in --events:", len(finished), [os.path.relpath(e["params"]["path"], out) for e in finished])
    started_ids = [e["params"]["id"] for e in events if e["method"] == "track.started"]
    print("last finished id is the last real take:", bool(finished) and finished[-1]["params"]["id"] in started_ids)
    try:
        print("config.toml:", open(cfg).read().strip().replace("\n", " | "))
    except FileNotFoundError:
        print("config.toml: not written")
    files = sorted(os.path.relpath(os.path.join(d, f), out) for d, _, fs in os.walk(out) for f in fs)
    print("files:", files)
    logtail = [l for l in open(os.path.join(W, "spytifyd.log")) if "idle" in l or "ended" in l]
    print("log:", "".join(logtail[-3:]).strip())


if __name__ == "__main__":
    sys.exit(main())
