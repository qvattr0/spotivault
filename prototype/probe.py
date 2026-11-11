#!/usr/bin/env python3
"""spotibackup feasibility probe.

Drives Spytify (JSON-RPC over its socket), the Spotify Web API and the Spotify
client's MPRIS interface, to check each risky piece of the design. Stdlib only.

    probe info                      Spytify version, target player, startup checks
    probe setup                     apply the recording defaults through settings.set
    probe auth --client-id ID       Web API login, step 1 (PKCE); prints the URL to open
    probe auth --callback URL       step 2: finish with the redirected page's address
    probe library                   playlists, saved albums, devices (and which endpoints answer)
    probe items URI                 track count of a playlist/album
    probe mpris                     what the client publishes over MPRIS
    probe record URI [--via mpris]  record one playlist/album end to end
"""
import argparse
import base64
import hashlib
import json
import os
import queue
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

STATE_DIR = os.environ.get("PROBE_STATE", os.path.expanduser("~/.probe"))
SPYTIFY_SOCKET = os.environ.get("SPYTIFY_SOCKET", "")
MPRIS_NAME = os.environ.get("SPYTIFY_TARGET_MPRIS", "org.mpris.MediaPlayer2.spotify")
REDIRECT_URI = os.environ.get("PROBE_REDIRECT_URI", "http://127.0.0.1:8888/callback")
SCOPES = " ".join([
    "playlist-read-private", "playlist-read-collaborative", "user-library-read",
    "user-read-playback-state", "user-modify-playback-state", "user-read-currently-playing",
])
API = "https://api.spotify.com/v1"

DEFAULT_SETTINGS = {
    "output.dir": "/music",
    "output.group_by": "artist/album",
    "encode.format": "aac",
    "encode.bitrate_kbps": 256,
    "recorder.duplicates": "skip",
    "recorder.skip_duplicates_forward": True,
    "recorder.stop_with_player": False,
    "privacy.bug_tracker": False,
    "app.check_updates": False,
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- Spytify

class SpytifyError(Exception):
    pass


class Spytify:
    """Newline-delimited JSON-RPC 2.0 client for spytifyd's socket."""

    def __init__(self, path=SPYTIFY_SOCKET):
        if not path:
            raise SystemExit("SPYTIFY_SOCKET is not set")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.rfile = self.sock.makefile("rb")
        self.lock = threading.Lock()
        self.pending = {}
        self.events = queue.Queue()
        self.next_id = 1
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.rfile:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).put(msg)
            elif "method" in msg:
                self.events.put(msg)
        self.events.put({"method": "_closed"})

    def call(self, method, params=None, timeout=15):
        with self.lock:
            rid = self.next_id
            self.next_id += 1
            box = queue.Queue(1)
            self.pending[rid] = box
            req = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
            self.sock.sendall((json.dumps(req) + "\n").encode())
        try:
            resp = box.get(timeout=timeout)
        except queue.Empty:
            raise SpytifyError(f"{method}: no answer in {timeout}s")
        if "error" in resp:
            raise SpytifyError(f"{method}: {resp['error']}")
        return resp.get("result")


# --------------------------------------------------------------------------- Web API

class WebAPI:
    def __init__(self):
        self.path = os.path.join(STATE_DIR, "token.json")
        try:
            with open(self.path) as f:
                self.tok = json.load(f)
        except FileNotFoundError:
            raise SystemExit("not logged in to the Web API: run `probe auth --client-id ...` first")

    @staticmethod
    def token_request(form):
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request("https://accounts.spotify.com/api/token", data=data,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)

    def save(self):
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.tok, f)
        os.chmod(self.path, 0o600)

    def refresh(self):
        new = self.token_request({"grant_type": "refresh_token", "client_id": self.tok["client_id"],
                                  "refresh_token": self.tok["refresh_token"]})
        self.tok["access_token"] = new["access_token"]
        self.tok["expires_at"] = time.time() + new.get("expires_in", 3600) - 60
        if new.get("refresh_token"):
            self.tok["refresh_token"] = new["refresh_token"]
        self.save()

    def req(self, method, path, params=None, body=None, retry=True):
        """Returns (status, parsed JSON or None). Never raises on HTTP errors."""
        if time.time() >= self.tok.get("expires_at", 0):
            self.refresh()
        url = path if path.startswith("http") else API + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else (b"" if method in ("PUT", "POST") else None)
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.tok["access_token"], "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
                try:
                    return r.status, (json.loads(raw) if raw.strip() else None)
                except ValueError:  # some player endpoints answer with plain text
                    return r.status, {"raw": raw.decode(errors="replace")[:300]}
        except urllib.error.HTTPError as e:
            if e.code == 401 and retry:
                self.refresh()
                return self.req(method, path, params, body, retry=False)
            if e.code == 429 and retry:
                time.sleep(int(e.headers.get("Retry-After", "2")))
                return self.req(method, path, params, body, retry=False)
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, {"raw": raw.decode(errors="replace")[:300]}


def parse_uri(uri):
    m = re.match(r"(?:spotify:|https?://open\.spotify\.com/)(playlist|album)[:/]([A-Za-z0-9]+)", uri)
    if not m:
        raise SystemExit(f"not a playlist/album URI or link: {uri}")
    return m.group(1), m.group(2), f"spotify:{m.group(1)}:{m.group(2)}"


def context_total(api, kind, cid):
    """Track count of a playlist/album, and which endpoint gave it."""
    if kind == "album":
        st, js = api.req("GET", f"/albums/{cid}/tracks", {"limit": 1})
        return (js or {}).get("total") if st == 200 else None, f"/albums/{{id}}/tracks -> {st}"
    tried = []
    for ep in ("items", "tracks"):  # /items is the Feb 2026 name; /tracks the old one
        st, js = api.req("GET", f"/playlists/{cid}/{ep}", {"limit": 1})
        tried.append(f"/playlists/{{id}}/{ep} -> {st}")
        if st == 200:
            return js.get("total"), "; ".join(tried)
    return None, "; ".join(tried)


def pick_device(api, name=None):
    st, js = api.req("GET", "/me/player/devices")
    devs = (js or {}).get("devices", []) if st == 200 else []
    # The client names its Connect device $DEVICE_NAME (hostname shim), else the hostname.
    # Other computers on the account show up too, so never fall back to "any Computer".
    name = name or os.environ.get("DEVICE_NAME") or socket.gethostname()
    devs = [d for d in devs if d["name"].lower() == name.lower()]
    return devs[0] if devs else None, st


# --------------------------------------------------------------------------- MPRIS

def mpris_get(prop):
    out = subprocess.run(
        ["dbus-send", "--session", "--print-reply", f"--dest={MPRIS_NAME}", "/org/mpris/MediaPlayer2",
         "org.freedesktop.DBus.Properties.Get", "string:org.mpris.MediaPlayer2.Player", f"string:{prop}"],
        capture_output=True, text=True, timeout=5)
    return out.stdout if out.returncode == 0 else None


def mpris_status():
    out = mpris_get("PlaybackStatus")
    m = re.search(r'string "(\w+)"', out or "")
    return m.group(1) if m else None


def mpris_call(method, *args):
    out = subprocess.run(["dbus-send", "--session", "--print-reply", f"--dest={MPRIS_NAME}",
                          "/org/mpris/MediaPlayer2", f"org.mpris.MediaPlayer2.Player.{method}", *args],
                         capture_output=True, text=True, timeout=5)
    return out.returncode == 0, (out.stderr or out.stdout).strip()


# --------------------------------------------------------------------------- commands

def cmd_info(a):
    info = Spytify().call("core.info")
    print(json.dumps(info, indent=2))


def cmd_setup(a):
    values = dict(DEFAULT_SETTINGS)
    if a.format:
        values["encode.format"] = a.format
    if a.bitrate:
        values["encode.bitrate_kbps"] = a.bitrate
    sp = Spytify()
    res = sp.call("settings.set", {"values": values})
    print(json.dumps(res, indent=2))
    if res and res.get("rejected"):
        # Retry rejected booleans as "on"/"off" strings, in case the recorder wants those.
        retry = {k: ("on" if v else "off") for k, v in values.items()
                 if k in res["rejected"] and isinstance(v, bool)}
        if retry:
            print("retrying booleans as on/off:", json.dumps(sp.call("settings.set", {"values": retry}), indent=2))


def cmd_auth(a):
    """Two steps, so it can run without a terminal:
    `auth --client-id ID` prints the login URL; `auth --callback URL` finishes it."""
    pending_path = os.path.join(STATE_DIR, "auth-pending.json")
    if not a.callback:
        if not a.client_id:
            raise SystemExit("give --client-id to start, or --callback to finish")
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(12)
        url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
            "client_id": a.client_id, "response_type": "code", "redirect_uri": REDIRECT_URI,
            "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state})
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(pending_path, "w") as f:
            json.dump({"client_id": a.client_id, "verifier": verifier, "state": state}, f)
        os.chmod(pending_path, 0o600)
        print("1. Open this URL in your browser and approve:\n\n" + url + "\n")
        print(f"2. The browser then goes to {REDIRECT_URI}?code=... and shows an error page. That's expected.")
        print("3. Run: probe auth --callback '<that page's full address>'")
        return
    try:
        with open(pending_path) as f:
            pend = json.load(f)
    except FileNotFoundError:
        raise SystemExit("no login in progress: run `probe auth --client-id ID` first")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(a.callback.strip()).query)
    if "error" in q:
        raise SystemExit("Spotify refused: " + q["error"][0])
    if q.get("state", [""])[0] != pend["state"]:
        raise SystemExit("state mismatch: paste the address from the latest login attempt")
    tok = WebAPI.token_request({"grant_type": "authorization_code", "code": q["code"][0],
                                "redirect_uri": REDIRECT_URI, "client_id": pend["client_id"],
                                "code_verifier": pend["verifier"]})
    os.remove(pending_path)
    api = WebAPI.__new__(WebAPI)
    api.path = os.path.join(STATE_DIR, "token.json")
    api.tok = {"client_id": pend["client_id"], "access_token": tok["access_token"],
               "refresh_token": tok["refresh_token"], "scope": tok.get("scope"),
               # Refresh tokens expire 6 months after this authorization; refreshing doesn't extend it.
               "authorized_at": time.time(),
               "expires_at": time.time() + tok.get("expires_in", 3600) - 60}
    api.save()
    st, me = api.req("GET", "/me")
    print(f"logged in: GET /me -> {st}", (me or {}).get("display_name") or (me or {}).get("id"))
    print("granted scopes:", tok.get("scope"))


def cmd_library(a):
    api = WebAPI()
    st, js = api.req("GET", "/me/playlists", {"limit": 50})
    print(f"GET /me/playlists -> {st}")
    if st == 200:
        print(f"  {js.get('total')} playlists; first {len(js['items'])}:")
        for p in js["items"]:
            if not p:
                continue
            tracks = p.get("items") or p.get("tracks") or {}
            print(f"  - {p['name']!r:45} {p['uri']}  owner={p['owner'].get('id')}  tracks={tracks.get('total')}")
    else:
        print("  ", js)
    st, js = api.req("GET", "/me/albums", {"limit": 50})
    print(f"GET /me/albums -> {st}")
    if st == 200:
        print(f"  {js.get('total')} saved albums; first {len(js['items'])}:")
        for it in js["items"]:
            al = it.get("album") or it.get("item") or {}
            print(f"  - {al.get('name')!r:45} {al.get('uri')}  tracks={al.get('total_tracks')}")
    else:
        print("  ", js)
    st, js = api.req("GET", "/me/player/devices")
    print(f"GET /me/player/devices -> {st}")
    for d in (js or {}).get("devices", []):
        print(f"  - {d['name']!r} type={d['type']} active={d['is_active']} id={d['id']}")


def cmd_items(a):
    kind, cid, _ = parse_uri(a.uri)
    total, how = context_total(WebAPI(), kind, cid)
    print(f"{kind} {cid}: total={total}  ({how})")


def cmd_mpris(a):
    for prop in ("PlaybackStatus", "Metadata", "CanControl", "CanPlay"):
        out = mpris_get(prop)
        print(f"--- {prop}\n{out.strip() if out else '(no answer: is the client running and on the bus?)'}")


def cmd_record(a):
    kind, cid, uri = parse_uri(a.uri)
    sp = Spytify()
    info = sp.call("core.info")
    log(f"spytify {info.get('version')} target={info.get('target')}")
    api = None
    try:
        api = WebAPI()
    except SystemExit as e:
        if a.via == "webapi":
            raise
        log(f"no Web API ({e}); end detection uses MPRIS only")

    total = None
    device = None
    if api:
        total, how = context_total(api, kind, cid)
        log(f"expected tracks: {total} ({how})")
        device, st = pick_device(api, a.device)
        log(f"device: {device and device['name']!r} (devices -> {st})")
        if a.via == "webapi" and not device:
            raise SystemExit("the container's Spotify client is not listed as a Web API device")

    for cmd in ("pause", "full_volume"):  # full volume, so no take is marked "(low volume)"
        try:
            sp.call("player.control", {"cmd": cmd})
        except SpytifyError as e:
            log(f"{cmd} before start: {e}")
    if api and device:
        for ep, params in (("/me/player/shuffle", {"state": "false"}), ("/me/player/repeat", {"state": "off"})):
            st, js = api.req("PUT", ep, dict(params, device_id=device["id"]))
            log(f"PUT {ep} -> {st}")

    started = sp.call("session.start", {})
    log(f"session.start -> {started}")
    if a.via == "webapi":
        st, js = api.req("PUT", "/me/player/play", {"device_id": device["id"]},
                         {"context_uri": uri, "offset": {"position": 0}, "position_ms": 0})
        log(f"PUT /me/player/play -> {st} {js or ''}")
    else:
        ok, out = mpris_call("OpenUri", f"string:{uri}")
        log(f"MPRIS OpenUri -> ok={ok} {out[:200]}")
        time.sleep(3)
        if mpris_status() != "Playing":
            ok, out = mpris_call("Play")
            log(f"MPRIS status after OpenUri was not Playing; Play -> ok={ok}")

    runlog = []
    counts = {"finished": 0, "skipped": 0}
    first_track_at = None
    idle_since = None
    last_poll = 0
    reason = None
    deadline = time.time() + a.max_minutes * 60
    def handle(ev):
        """Log and count one Spytify event. Returns the session state it reports, if any."""
        nonlocal first_track_at
        m, p = ev.get("method"), ev.get("params") or {}
        if m != "level":
            runlog.append({"t": time.time(), **ev})
        if m == "track.started":
            first_track_at = first_track_at or time.time()
            log(f"started  {p.get('artist')} - {p.get('title')} ({p.get('length_ms', 0)//1000}s)")
        elif m == "track.finished":
            counts["finished"] += 1
            log(f"finished {p.get('path')} ({p.get('bytes', 0)//1024} KiB)")
        elif m == "track.skipped":
            counts["skipped"] += 1
            log(f"skipped  {p.get('id')} reason={p.get('reason')}")
        elif m in ("error", "session.state", "target.state"):
            log(f"{m} {json.dumps(p)}")
        elif m == "_closed":
            return "closed"
        return p.get("state") if m == "session.state" else None

    def wait_idle(secs):
        end = time.time() + secs
        while time.time() < end:
            try:
                if handle(sp.events.get(timeout=1)) in ("idle", "closed"):
                    return True
            except queue.Empty:
                pass
            if sp.call("session.status").get("state") == "idle":
                return True
        return False

    while not reason:
        try:
            if handle(sp.events.get(timeout=1)) == "closed":
                reason = "spytify socket closed"
        except queue.Empty:
            pass
        now = time.time()
        if total and counts["finished"] + counts["skipped"] >= total:
            reason = f"all {total} tracks accounted for (finished+skipped)"
        elif now > deadline:
            reason = f"--max-minutes {a.max_minutes} reached"
        elif now - last_poll >= 5:
            last_poll = now
            status = mpris_status()
            ctx = None
            if api and first_track_at:  # poll the Web API only once a track has started
                st, js = api.req("GET", "/me/player")
                ctx = ((js or {}).get("context") or {}).get("uri") if st == 200 else None
                if first_track_at and st == 200 and js and ctx and ctx != uri:
                    reason = f"Web API context moved on to {ctx} (autoplay?)"
            if first_track_at and status != "Playing":
                idle_since = idle_since or now
                if now - idle_since >= a.idle:
                    reason = f"MPRIS status {status!r} for {a.idle}s"
            else:
                idle_since = None
    log(f"end detected: {reason}")
    try:
        res = sp.call("session.stop", {"now": "context moved" in reason or "max-minutes" in reason}, timeout=30)
        log(f"session.stop -> {res}")
    except SpytifyError as e:
        log(f"session.stop: {e}")
    if "context moved" in reason:
        sp.call("player.control", {"cmd": "pause"})
    # Spotify only *pauses* at the end of a playlist/album, so Spytify never closes the last
    # track by itself. It does when the audio stream ends or the player goes away.
    finalized_by = None
    if wait_idle(8):
        finalized_by = "session ended by itself"
    else:
        # Ending the audio stream does not help (tested): Spytify just waits for a new one.
        # The player going away does, so restart the client; it comes back logged in.
        out = subprocess.run(["supervisorctl", "-c", "/etc/supervisor/spotibackup.conf", "restart", "spotify"],
                             capture_output=True, text=True)
        log(f"last track still open: restarted the Spotify client ({' '.join(out.stdout.split())})")
        finalized_by = "restarted the Spotify client" if wait_idle(30) else "NOT finalized"
    log(f"last track: {finalized_by}")
    status = sp.call("session.status")
    os.makedirs(os.path.join(STATE_DIR, "runs"), exist_ok=True)
    out = os.path.join(STATE_DIR, "runs", time.strftime("%Y%m%d-%H%M%S") + f"-{cid}.json")
    with open(out, "w") as f:
        json.dump({"uri": uri, "via": a.via, "expected": total, "counts": counts, "end_reason": reason,
                   "finalized_by": finalized_by,
                   "final_status": status, "events": runlog}, f, indent=1)
    log(f"summary: expected={total} finished={counts['finished']} skipped={counts['skipped']}; log: {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info").set_defaults(fn=cmd_info)
    p = sub.add_parser("setup")
    p.add_argument("--format", choices=["mp3", "aac", "flac", "wav"])
    p.add_argument("--bitrate", type=int, choices=[128, 160, 256, 320])
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("auth")
    p.add_argument("--client-id", help="start a login with this app's Client ID")
    p.add_argument("--callback", help="finish the login with the redirected page's full address")
    p.set_defaults(fn=cmd_auth)
    sub.add_parser("library").set_defaults(fn=cmd_library)
    p = sub.add_parser("items")
    p.add_argument("uri")
    p.set_defaults(fn=cmd_items)
    sub.add_parser("mpris").set_defaults(fn=cmd_mpris)
    p = sub.add_parser("record")
    p.add_argument("uri", help="spotify:playlist:ID, spotify:album:ID or an open.spotify.com link")
    p.add_argument("--via", choices=["webapi", "mpris"], default="webapi", help="how to start playback")
    p.add_argument("--device", help="Web API device name to use (default: the Computer device)")
    p.add_argument("--idle", type=int, default=20, help="seconds not playing before the run counts as over")
    p.add_argument("--max-minutes", type=int, default=120)
    p.set_defaults(fn=cmd_record)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
