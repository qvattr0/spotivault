#!/usr/bin/env python3
"""spotivault feasibility probe.

Drives Spytify (JSON-RPC over its socket), the Spotify Web API and the Spotify
client's MPRIS interface, to check each risky piece of the design. Stdlib only.

    probe info                      Spytify version, target player, startup checks
    probe setup                     apply the recording defaults through settings.set
    probe auth --client-id ID       Web API login, step 1 (PKCE); prints the URL to open
    probe auth --callback URL       step 2: finish with the redirected page's address
    probe library                   playlists, saved albums, devices (and which endpoints answer)
    probe items URI                 track count of a playlist/album
    probe mpris                     what the client publishes over MPRIS
    probe record URI [--via mpris]  record one playlist/album end to end, with a --once recorder
    probe record URI --only-missing play only the tracks Spytify's index doesn't have yet
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
OUTPUT_DIR = os.environ.get("SPYTIFY_OUTPUT_DIR", "/music")

DEFAULT_SETTINGS = {
    "output.dir": "/music",
    # /music/<artist>/<album>/<track> - <title>.m4a. {track} is two digits ("05"); a track
    # with no number drops it and its " - ". The album folder gets " (year)" when the player
    # gives a year, which the Linux client hasn't so far.
    "output.group_by": "artist/album",
    "output.template": "{track} - {title}",
    "output.prefix": "none",
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


def context_tracks(api, kind, cid):
    """The item's tracks in play order, as (status, list). Each entry: position (the context
    offset), uri, name, artists, duration_ms, playable. Followed playlists answer 403."""
    out = []
    if kind == "album":
        url, params = f"/albums/{cid}/tracks", {"limit": 50, "market": "from_token"}
    else:
        url, params = f"/playlists/{cid}/items", {"limit": 50, "market": "from_token"}
    while url:
        st, js = api.req("GET", url, params)
        if st != 200:
            return st, None
        for e in js.get("items", []):
            # Playlist entries carry the track under `item` (Feb 2026 API), `track` before that.
            t = e if kind == "album" else (e.get("item") or e.get("track") or {})
            out.append({
                "position": len(out), "uri": t.get("uri"), "name": t.get("name") or "",
                "artists": [a.get("name", "") for a in t.get("artists") or []],
                "duration_ms": t.get("duration_ms") or 0,
                # Unplayable tracks are passed over by the client (an offset at one plays
                # another track); local files and episodes are not recorded.
                "playable": (t.get("type") == "track" and not t.get("is_local")
                             and t.get("is_playable", True) is not False),
                "linked_from": (t.get("linked_from") or {}).get("uri"),
            })
        url, params = js.get("next"), None
    return 200, out


# --------------------------------------------------------------------------- Spytify's duplicate index

def go_lower(s):
    """Go's strings.ToLower: per-rune simple case mapping. Python's str.lower() differs for
    U+0130 (İ -> 'i̇', two runes) and for a final Σ (-> ς); Go gives 'i' and 'σ'."""
    return "".join("i" if c == "İ" else c.lower() for c in s)


def go_trim(s):
    """Go's strings.TrimSpace (unicode.IsSpace). Python's strip() also strips U+001C..U+001F."""
    return s.strip(" \t\n\v\f\r\x85\xa0         "
                   "       　")


def track_key(artist, title):
    """Spytify's trackKey (internal/core/records.go): first artist + U+001F + title,
    each trimmed and lowercased. Spotify's MPRIS `xesam:artist` holds only the first artist,
    so a Web API track's key is artists[0].name + name."""
    return go_lower(go_trim(artist)) + "\x1f" + go_lower(go_trim(title))


def web_track_key(t):
    return track_key(t["artists"][0] if t["artists"] else "", t["name"])


def recorded_index(output_dir=None):
    """Spytify's duplicate index, <output>/.spytify/recorded.jsonl: key -> path, later lines
    winning. Like recordIndex.lookup, an entry only counts while its file exists."""
    path = os.path.join(output_dir or OUTPUT_DIR, ".spytify", "recorded.jsonl")
    idx = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    idx[e["Key"]] = e["Path"]
                except (ValueError, KeyError, TypeError):
                    continue
    except FileNotFoundError:
        pass
    return {k: p for k, p in idx.items() if os.path.exists(p)}


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


SUPERVISORCTL = ["supervisorctl", "-c", "/etc/supervisor/spotivault.conf"]


def supervisor(*args):
    out = subprocess.run(SUPERVISORCTL + list(args), capture_output=True, text=True)
    return " ".join(out.stdout.split())


def cmd_record(a):
    """Record one playlist/album with its own `spytifyd --once --serve --idle-exit` process.

    Spotify only pauses at the end of a context. The always-running recorder never closes
    the last take then; a --once recorder does, once the player has been idle for --idle s.
    """
    kind, cid, uri = parse_uri(a.uri)
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

    # --only-missing: play only the tracks Spytify's index doesn't have. `uris` playback doesn't
    # work on the Linux client (204, then it loads nothing), so this plays the context from the
    # first missing track, and jumps over recorded ones with an `offset` play of its own.
    plan = None      # context positions to record, in order
    tracks = None
    if a.only_missing:
        if not (api and device and a.via == "webapi"):
            raise SystemExit("--only-missing needs the Web API (and --via webapi)")
        st, tracks = context_tracks(api, kind, cid)
        if st != 200:
            log(f"track list -> {st} (a followed playlist?): can't tell what's missing; "
                f"playing the whole {kind} with skip-forward instead")
        else:
            idx = recorded_index()
            only = set(a.positions or [])
            plan, have, unplayable = [], [], []
            for t in tracks:
                if not t["playable"]:
                    unplayable.append(t["position"] + 1)
                elif web_track_key(t) in idx:
                    have.append(t["position"] + 1)
                elif not only or t["position"] + 1 in only:
                    plan.append(t["position"])
            log(f"{len(tracks)} tracks: {len(have)} recorded, {len(unplayable)} unplayable "
                f"{unplayable or ''}, to record: {[p + 1 for p in plan]}")
            if not plan:
                log("nothing missing: not starting a recorder")
                return
            total = len(plan)

    if api and device:
        # A track the player is paused on past 300 ms is "already playing" to a new session
        # (startFromInitial): Spytify won't record it, and an offset play of that same track
        # names no new track, so it stays unrecorded. That's the retry case: an earlier run
        # paused mid-track. Paused at 0, it is recorded once it plays.
        st_p, _ = api.req("PUT", "/me/player/pause", {"device_id": device["id"]})
        st_s, _ = api.req("PUT", "/me/player/seek", {"position_ms": 0, "device_id": device["id"]})
        log(f"before the recorder: pause -> {st_p}, seek to 0 -> {st_s}")

    # The supervisord daemon owns the socket; hand it over to a --once recorder for this run.
    log(f"supervisord spytifyd: {supervisor('stop', 'spytifyd')}")
    os.makedirs("/config/logs", exist_ok=True)
    cmd = ["/usr/bin/spytifyd", "--once", "--serve", "--idle-exit", f"{a.idle}s",
           "--wait-target", "60s", "--log-file", "/config/logs/spytifyd-once.log"]
    if plan is not None:
        # The controller skips recorded tracks itself; Spytify's Next would restart a paused player.
        cmd += ["--set", "recorder.skip_duplicates_forward=false"]
    out_log = open("/config/logs/spytifyd-once.stdout", "ab")
    proc = subprocess.Popen(cmd, stdout=out_log, stderr=subprocess.STDOUT)
    log(f"started {' '.join(cmd[1:])} (pid {proc.pid})")
    sp = None
    for _ in range(40):
        try:
            sp = Spytify()
            break
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.25)
    if not sp:
        supervisor("start", "spytifyd")
        raise SystemExit(f"--once recorder didn't open its socket (exit code {proc.poll()})")
    info = sp.call("core.info")
    log(f"spytify {info.get('version')} target={info.get('target')}")

    try:
        sp.call("player.control", {"cmd": "full_volume"})  # so no take is marked "(low volume)"
    except SpytifyError as e:
        log(f"full_volume: {e}")
    if api and device:
        for ep, params in (("/me/player/shuffle", {"state": "false"}), ("/me/player/repeat", {"state": "off"})):
            st, js = api.req("PUT", ep, dict(params, device_id=device["id"]))
            log(f"PUT {ep} -> {st}")
    t_play = time.time()
    started, jumped = set(), set()   # plan positions seen starting / jumped to
    if a.via == "webapi":
        start_at = plan[0] if plan else 0
        jumped.add(start_at)
        st, js = api.req("PUT", "/me/player/play", {"device_id": device["id"]},
                         {"context_uri": uri, "offset": {"position": start_at}, "position_ms": 0})
        log(f"PUT /me/player/play offset={start_at} -> {st} {js or ''}")
    else:
        ok, out = mpris_call("OpenUri", f"string:{uri}")
        log(f"MPRIS OpenUri -> ok={ok} {out[:200]}")
        time.sleep(3)
        if mpris_status() != "Playing":
            ok, out = mpris_call("Play")
            log(f"MPRIS status after OpenUri was not Playing; Play -> ok={ok}")

    runlog = []
    counts = {"finished": 0, "skipped": 0}
    finished_paths = set()
    jumps = []
    first_track_at = None
    end_seen_at = None     # when the controller first saw the item end (paused, or all counted)
    reason = None          # why the controller stepped in, if it did
    term_sent = None
    last_poll = 0
    deadline = time.time() + a.max_minutes * 60

    def loaded_positions(title):
        """Which of the item's positions is loaded: the Web API's item once its name agrees
        with the event's title (it can lag a moment), else the tracks with that title."""
        want = go_lower(title or "")
        for _ in range(6):
            st, js = api.req("GET", "/me/player", {"market": "from_token"})
            it = (js or {}).get("item") or {}
            if st == 200 and go_lower(it.get("name") or "") == want:
                uris = {it.get("uri"), (it.get("linked_from") or {}).get("uri")} - {None}
                hits = [t["position"] for t in tracks if t["uri"] in uris or t["linked_from"] in uris]
                if hits:
                    return hits
            time.sleep(0.5)
        return [t["position"] for t in tracks if go_lower(t["name"]) == want]

    def steer(title):
        """On each track start: stay if it's a planned track, else jump to the next planned
        one, or pause when none is left (the recorder's idle exit then ends the item)."""
        hits = loaded_positions(title)
        planned = [p for p in hits if p in plan and p not in started]
        if planned:
            started.add(planned[0])
            return
        nxt = next((p for p in plan if p not in started and p not in jumped), None)
        status = mpris_status()
        where = f"track {hits[0] + 1}" if hits else "an unknown track"
        if nxt is None:
            if status == "Playing":
                ok, _ = mpris_call("Pause")
                log(f"plan: {where} is not on the plan and nothing is left: paused (ok={ok})")
                jumps.append({"t": time.time(), "at": hits, "action": "pause"})
            return
        if status != "Playing":
            log(f"plan: {where} loaded while {status}: not jumping")
            return
        jumped.add(nxt)
        st, js = api.req("PUT", "/me/player/play", {"device_id": device["id"]},
                         {"context_uri": uri, "offset": {"position": nxt}, "position_ms": 0})
        log(f"plan: {where} is not on the plan: jump to track {nxt + 1} -> {st}")
        jumps.append({"t": time.time(), "at": hits, "action": f"jump {nxt + 1}", "status": st})

    def handle(ev):
        nonlocal first_track_at
        m, p = ev.get("method"), ev.get("params") or {}
        if m != "level":
            runlog.append({"t": time.time(), **ev})
        if m == "track.started":
            first_track_at = first_track_at or time.time()
            log(f"started  {p.get('artist')} - {p.get('title')} ({p.get('length_ms', 0)//1000}s)")
            if plan:
                steer(p.get("title"))
        elif m == "track.finished":
            counts["finished"] += 1
            finished_paths.add(p.get("path"))
            log(f"finished {p.get('path')} ({p.get('bytes', 0)//1024} KiB, "
                f"{p.get('duration_ms', 0)/1000:.1f}s)")
        elif m == "track.skipped":
            counts["skipped"] += 1
            log(f"skipped  {p.get('id')} reason={p.get('reason')}")
        elif m in ("error", "session.state", "target.state"):
            log(f"{m} {json.dumps(p)}")
        elif m == "_closed":
            return "closed"
        return None

    while True:
        try:
            if handle(sp.events.get(timeout=1)) == "closed":
                break
        except queue.Empty:
            pass
        if proc.poll() is not None:
            break
        now = time.time()
        if term_sent:
            if now - term_sent > 45:
                proc.kill()
                log("recorder ignored SIGTERM for 45 s: killed")
            continue
        if now - last_poll < 5:
            continue
        last_poll = now
        status = mpris_status()
        # With a plan, skips are the recorded tracks jumped over: only finished ones count.
        accounted = counts["finished"] + (0 if plan else counts["skipped"])
        if first_track_at and (status != "Playing" or (total and accounted >= total)):
            if not end_seen_at:
                end_seen_at = now
                log(f"item looks over: MPRIS {status!r}, {accounted}/{total} accounted for; "
                    f"waiting for the recorder's {a.idle}s idle exit")
        elif status == "Playing":
            end_seen_at = None
        if api and first_track_at:
            st, js = api.req("GET", "/me/player")
            ctx = ((js or {}).get("context") or {}).get("uri") if st == 200 else None
            if st == 200 and ctx and ctx != uri:
                reason = f"Web API context moved on to {ctx} (autoplay?)"
                sp.call("player.control", {"cmd": "pause"})
                # The take in progress belongs to the next context: drop it, end the session.
                res = sp.call("session.stop", {"now": True}, timeout=30)
                log(f"{reason}: paused, session.stop now -> {res}")
                term_sent = now
                continue
        if not first_track_at and now - t_play > 90:
            reason = "playback never started (the idle exit only counts after the player has played)"
        elif end_seen_at and now - end_seen_at > a.idle + 60:
            reason = f"recorder still running {a.idle + 60}s after the item ended"
        elif now > deadline:
            reason = f"--max-minutes {a.max_minutes} reached"
        if reason:
            proc.terminate()  # SIGTERM finishes the take in progress; a second one stops at once
            term_sent = now
            log(f"{reason}: sent SIGTERM")

    code = proc.wait()
    # The last take is saved as the recorder exits: read what's left of its events.
    while True:
        try:
            if handle(sp.events.get(timeout=1)) == "closed":
                break
        except queue.Empty:
            break
    # At the end of a context Spotify loads track 1 paused. The idle exit then takes it as a new
    # (duplicate) take, and recorder.skip_duplicates_forward presses Next, so the player starts
    # track 2 as the recorder exits. Pause it again.
    time.sleep(2)
    if mpris_status() == "Playing":
        ok, _ = mpris_call("Pause")
        log(f"player was playing again after the recorder exited: paused (ok={ok})")
    finalized_by = reason or "recorder's idle exit"
    log(f"recorder exited with code {code}, "
        f"{time.time() - end_seen_at:.0f}s after the item ended" if end_seen_at else
        f"recorder exited with code {code}")
    still_missing = None
    if plan:
        idx = recorded_index()
        still_missing = [p + 1 for p in plan if web_track_key(tracks[p]) not in idx]
        log(f"plan {[p + 1 for p in plan]}: {len(finished_paths)} distinct files saved, "
            f"still missing {still_missing or 'none'}"
            + (" -> would go back in the queue" if still_missing else ""))
    else:
        accounted = counts["finished"] + counts["skipped"]
        if total and accounted < total:
            log(f"only {accounted}/{total} tracks accounted for: the item ended early (a long pause?) "
                "and would go back in the queue")
    log(f"supervisord spytifyd: {supervisor('start', 'spytifyd')}")

    os.makedirs(os.path.join(STATE_DIR, "runs"), exist_ok=True)
    path = os.path.join(STATE_DIR, "runs", time.strftime("%Y%m%d-%H%M%S") + f"-{cid}.json")
    with open(path, "w") as f:
        json.dump({"uri": uri, "via": a.via, "mode": "once" + ("+only-missing" if plan else ""),
                   "expected": total, "counts": counts, "distinct_finished": sorted(finished_paths),
                   "plan": [p + 1 for p in plan] if plan else None, "still_missing": still_missing,
                   "jumps": jumps, "controller_stepped_in": reason, "finalized_by": finalized_by,
                   "exit_code": code, "events": runlog}, f, indent=1)
    log(f"summary: expected={total} finished={counts['finished']} skipped={counts['skipped']}; log: {path}")


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
    p.add_argument("--idle", type=int, default=20, help="--idle-exit for the recorder: seconds idle before it ends the item")
    p.add_argument("--max-minutes", type=int, default=120)
    p.add_argument("--only-missing", action="store_true",
                   help="play only the tracks missing from Spytify's index, skip-forward off "
                        "(albums and owned playlists; others play whole)")
    p.add_argument("--positions", type=lambda s: [int(x) for x in s.split(",")],
                   help="with --only-missing, consider only these 1-based track numbers (for tests)")
    p.set_defaults(fn=cmd_record)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
