#!/usr/bin/env bash
# shellcheck disable=SC2016 # single-quoted scripts run inside the container
# Container smoke test, run by CI and by hand:
#
#   image/test/smoke.sh IMAGE [--install]
#
# Starts IMAGE as a fresh container, with /music mapped to a new named volume (as a shared folder
# would be) and /config left to an anonymous one, then checks:
#   1. it turns healthy, and /api/health sees the database, the screen and PulseAudio;
#   2. only s6's supervision tree (started by /init) runs as root, and the controller runs as app;
#   3. WS /vnc reaches the VNC server (RFB 003.008), /vnc.html and noVNC's core are served, and the
#      web UI is: / and a deep link answer with index.html, and the hashed script it names loads;
#   4. the controller's venv is byte-compiled, read-only for app and has no pip;
#   5. the setup endpoints of wizard steps 1, 2, 4 and 6 answer through curl;
#   6. spytifyd reports the pinned version, and the DEVICE_NAME shim works;
#   7. spytifyd --fake records AAC, MP3 and FLAC with the image's ffmpeg;
#   8. bad settings stop the container with a clear message;
#   9. with --install: the controller installs the client and WS /api/events shows the progress,
#      spotify-install agrees, s6 starts the client with the shim loaded, the controller sees its
#      window (not logged in) and restarts it, and a stop with the client running is quick;
#  10. after a restart, links an app process planted in /config (init's log, the machine ID)
#      haven't let init-spotivault write to root's files.
# Prints a size report at the end, and appends it to $GITHUB_STEP_SUMMARY when set.
#
# SMOKE_PORT publishes on that host port (default: a free one); SMOKE_NAME names the container.
set -euo pipefail

image="${1:?usage: smoke.sh IMAGE [--install]}"
install=0
[ "${2:-}" = --install ] && install=1
here="$(cd "$(dirname "$0")" && pwd)"
name="${SMOKE_NAME:-spotivault-smoke-$$}"
spytify_version="${SPYTIFY_VERSION:-2.0.2}"
venv_python=/opt/spotivault/venv/bin/python
tmp="$(mktemp -d)"
failed=0
watcher=""

pass() { printf '  ok    %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; failed=1; }
step() { printf '\n== %s\n' "$*"; }
in_app() { docker exec -u app "$name" "$@"; }
# Runs a Python file from image/test/ inside the container, with the controller's Python.
in_venv() { local script="$1"; shift; docker exec -i -u app "$name" "$venv_python" -I - "$@" <"$here/$script"; }

# client_pid: the Spotify client's main process, or nothing. Its Chromium helpers are named
# `spotify` too; they're the ones with a --type= argument (as client/status.py tells them apart).
client_pid() {
    in_app sh -c 'for d in /proc/[0-9]*; do
        [ "$(cat "$d/comm" 2>/dev/null)" = spotify ] || continue
        args="$(tr "\0" "\n" <"$d/cmdline" 2>/dev/null)" || continue
        [ -n "$args" ] || continue
        printf "%s\n" "$args" | grep -q "^--type=" && continue
        echo "${d#/proc/}"
    done' 2>/dev/null | sort -n | head -n 1 || true
}
# api METHOD PATH [JSON]: calls the controller. Sets $code; the body is in $tmp/body.
api() {
    local args=(-sS -o "$tmp/body" -w '%{http_code}' -X "$1" --max-time 30)
    [ $# -ge 3 ] && args+=(-H 'Content-Type: application/json' --data "$3")
    code="$(curl "${args[@]}" "http://127.0.0.1:$port$2" 2>"$tmp/curl.err")" || code=000
}
# json EXPR: a Python expression on the last body, which it sees as `j`. Prints its value.
json() {
    python3 -c 'import json, sys; j = json.load(open(sys.argv[1])); print(eval(sys.argv[2]))' \
        "$tmp/body" "$1" 2>/dev/null || echo "?"
}
# expect WHAT STATUS EXPR METHOD PATH [JSON]: passes when the controller answers STATUS and EXPR
# holds for the body (an empty EXPR checks only the status). Sets $ok to 1 or 0.
expect() {
    local what="$1" want="$2" expr="$3"
    shift 3
    api "$@"
    ok=0
    if [ "$code" != "$want" ]; then
        fail "$what: HTTP $code, expected $want: $(head -c 300 "$tmp/body" 2>/dev/null; cat "$tmp/curl.err")"
    elif [ -n "$expr" ] && [ "$(json "$expr")" != True ]; then
        fail "$what: $(head -c 300 "$tmp/body")"
    else
        pass "$what"
        ok=1
    fi
}

cleanup() {
    if [ "$failed" = 1 ]; then
        echo; echo "--- container log (last 80 lines)"; docker logs --tail 80 "$name" 2>&1 || true
    fi
    if [ -n "$watcher" ]; then kill "$watcher" 2>/dev/null || true; fi
    docker rm -fv "$name" >/dev/null 2>&1 || true
    docker volume rm "$name-music" >/dev/null 2>&1 || true
    rm -rf "$tmp"
}
trap cleanup EXIT

step "start $image"
docker run -d --name "$name" --shm-size 1g -p "127.0.0.1:${SMOKE_PORT:-}:8080" \
    -v "$name-music:/music" -e DEVICE_NAME=spotivault-smoke "$image" >/dev/null
port="$(docker port "$name" 8080/tcp | head -n 1)"
port="${port##*:}"
echo "  published on 127.0.0.1:$port"
image_version="$(docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$image" |
    sed -n 's/^SPOTIVAULT_IMAGE_VERSION=//p')"

if [ "$install" = 1 ]; then
    # Watch WS /api/events from the start, so the whole install is seen: the controller may start
    # it by itself on its first start. The result is read in step 9.
    in_venv install_events.py 600 >"$tmp/install-events.json" 2>&1 &
    watcher=$!
fi

step "1. health"
status=""
for _ in $(seq 1 90); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$name" 2>/dev/null || echo gone)"
    [ "$status" = healthy ] || [ "$status" = gone ] && break
    sleep 2
done
if [ "$status" = healthy ]; then pass "healthy"; else fail "health is '$status'"; exit 1; fi
curl -fsS "http://127.0.0.1:$port/api/health" && echo
expect "GET /api/health: ok, with the database, the screen and PulseAudio" 200 \
    "j['status'] == 'ok' and j['checks']['db'] == j['checks']['display'] == j['checks']['pulseaudio'] == 'ok'" \
    GET /api/health

step "2. only s6 (from /init) runs as root"
# Read /proc as app, so the check itself isn't a root process. Each line: uid pid comm cmdline.
procs="$(in_app sh -c 'for d in /proc/[0-9]*; do
    u=$(awk "/^Uid:/ {print \$2}" "$d/status" 2>/dev/null) || continue
    [ -n "$u" ] && printf "%s %s %s %s\n" "$u" "${d#/proc/}" "$(cat "$d/comm" 2>/dev/null)" \
        "$(tr "\0" " " <"$d/cmdline" 2>/dev/null)"
done')"
root="$(awk '$1 == 0 {print $3}' <<<"$procs" | sort | uniq -c)"
while read -r line; do echo "        root: $line"; done <<<"$root"
bad="$(awk '$1 == 0 && $3 !~ /^s6-(svscan|supervise|linux-init-s|fdholderd|ipcserverd)$/ {print $2 "/" $3}' <<<"$procs")"
if [ -z "$bad" ]; then pass "every other process runs as app"; else fail "root processes outside s6: $bad"; fi
for svc in Xvfb x11vnc matchbox-window pulseaudio dbus-daemon; do
    if awk -v s="$svc" '$1 == 1000 && index($3, s) == 1 {found = 1} END {exit !found}' <<<"$procs"; then
        pass "$svc runs as app"
    else
        fail "$svc isn't running as app"
    fi
done
# The controller's process is named after its interpreter, so look for its command line.
if awk '$1 == 1000 && index($0, " -m spotivault ") {found = 1} END {exit !found}' <<<"$procs"; then
    pass "the controller (python -m spotivault) runs as app"
else
    fail "the controller (python -m spotivault) isn't running as app"
fi

step "3. WS /vnc reaches VNC"
banner="$(python3 - "$port" <<'EOF'
import base64, os, socket, sys
port = int(sys.argv[1])
s = socket.create_connection(("127.0.0.1", port), timeout=10)
key = base64.b64encode(os.urandom(16)).decode()
s.sendall((
    "GET /vnc HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
    "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: binary\r\n\r\n" % (port, key)
).encode())
buf = b""
while b"\r\n\r\n" not in buf:
    buf += s.recv(4096)
head, rest = buf.split(b"\r\n\r\n", 1)
if b" 101 " not in head.split(b"\r\n")[0]:
    sys.exit("no upgrade: " + head.split(b"\r\n")[0].decode())
while len(rest) < 2:
    rest += s.recv(4096)
n = rest[1] & 0x7F
while len(rest) < 2 + n:
    rest += s.recv(4096)
print(rest[2:2 + n].decode().strip())
EOF
)" || true
if [[ "$banner" == "RFB 003.008" ]]; then pass "$banner"; else fail "VNC banner: '$banner'"; fi
# The controller's /vnc.html page, and noVNC's core from the image's web root.
api GET /vnc.html
if [ "$code" = 200 ] && grep -q "novnc/core/rfb.js" "$tmp/body"; then pass "GET /vnc.html"; else fail "GET /vnc.html: HTTP $code"; fi
api GET /novnc/core/rfb.js
if [ "$code" = 200 ] && grep -q "export default class RFB" "$tmp/body"; then
    pass "GET /novnc/core/rfb.js"
else
    fail "GET /novnc/core/rfb.js: HTTP $code"
fi

# The web UI (S7, built into the web root): GET / is the SPA's index.html, the hashed script it names
# loads, and an app route (/library) gets index.html too, not a 404. A missing asset is a 404.
api GET /
if [ "$code" = 200 ] && grep -q '<div id="root">' "$tmp/body"; then
    cp "$tmp/body" "$tmp/index.html"
    pass "GET /: the web UI's index.html"
else
    fail "GET /: HTTP $code, not the web UI's index.html"
fi
asset="$(grep -o 'src="/assets/[^"]*\.js"' "$tmp/index.html" 2>/dev/null | head -n 1 | sed 's/^src="//; s/"$//' || true)"
if [ -n "$asset" ]; then
    api GET "$asset"
    if [ "$code" = 200 ] && [ -s "$tmp/body" ]; then pass "GET $asset: the hashed script from index.html"; else fail "GET $asset: HTTP $code"; fi
else
    fail "index.html names no /assets/*.js script"
fi
api GET /library
if [ "$code" = 200 ] && cmp -s "$tmp/body" "$tmp/index.html"; then
    pass "GET /library (a deep link): index.html"
else
    fail "GET /library: HTTP $code, not index.html"
fi
api GET /assets/no-such-file.js
if [ "$code" = 404 ]; then pass "GET /assets/no-such-file.js: 404, not index.html"; else fail "GET /assets/no-such-file.js: HTTP $code"; fi

step "4. the controller's venv"
# Every module has a valid .pyc (app can't write one), app can't change the venv, and no pip.
if out="$(in_venv venv_check.py 2>&1)"; then
    pass "byte-compiled, read-only for app, no pip: $out"
else
    fail "venv: $out"
fi

step "5. setup endpoints (wizard steps 1, 2, 4 and 6)"
expect "GET /api/setup: 9 steps, not completed" 200 \
    "[s['id'] for s in j['steps']][:2] == ['tos', 'client'] and len(j['steps']) == 9 and j['completed'] is False" \
    GET /api/setup
# Step 1: the Terms notice. The acknowledgement keeps its first timestamp.
expect "step 1: POST /api/setup/tos" 200 \
    "j['tos_acknowledged_at'] is not None and j['steps'][0]['state'] == 'done' and j['first_unfinished'] != 'tos'" \
    POST /api/setup/tos '{"understood": true}'
acknowledged="$(json "j['tos_acknowledged_at']")"
expect "step 1: acknowledging again keeps the first timestamp" 200 \
    "j['tos_acknowledged_at'] == '$acknowledged'" POST /api/setup/tos '{"understood": true}'
expect "step 1: understood=false is refused" 422 "j['error']['code'] == 'validation_failed'" \
    POST /api/setup/tos '{"understood": false}'
# Step 2: the client's state. With --install, step 9 installs it.
expect "step 2: GET /api/client/status" 200 \
    "isinstance(j['installed'], bool) and j['device_name'] == 'spotivault-smoke' and j['install']['state'] in ('not_started', 'installing', 'installed', 'failed')" \
    GET /api/client/status
# Step 4: the checklist. Tick every Confirm row; ticking another kind of row is refused.
expect "step 4: GET /api/client/checklist" 200 \
    "len(j['rows']) > 0 and all(r['check'] in ('auto', 'confirm', 'set_for_you') for r in j['rows'])" \
    GET /api/client/checklist
if [ "$ok" = 1 ]; then
    confirm="$(json "json.dumps({'rows': {r['id']: True for r in j['rows'] if r['check'] == 'confirm'}})")"
    other="$(json "next((r['id'] for r in j['rows'] if r['check'] != 'confirm'), '')")"
    expect "step 4: POST /api/setup/checklist/confirm $confirm" 200 \
        "all(r['confirmed'] is True for r in j['rows'] if r['check'] == 'confirm')" \
        POST /api/setup/checklist/confirm "$confirm"
    if [ -n "$other" ]; then
        expect "step 4: ticking $other (not a Confirm row) is refused" 422 \
            "j['error']['code'] == 'validation_failed'" \
            POST /api/setup/checklist/confirm "{\"rows\": {\"$other\": true}}"
    fi
fi
# Step 6: the music folder and the format. /music is a mapped volume here, so it passes; /config
# is an anonymous volume, which doesn't count as mounted (nothing is mapped there).
expect "step 6: GET /api/storage: /music mounted and writable, /config not mapped" 200 \
    "j['music']['path'] == '/music' and j['music']['mounted'] and j['music']['writable'] and j['music']['error'] is None and j['config']['path'] == '/config' and j['config']['mounted'] is False and j['ok'] == (j['music']['free_bytes'] >= j['min_free_bytes'])" \
    GET /api/storage
expect "step 6: GET /api/settings: AAC 256 by default" 200 \
    "j['format'] == 'aac' and j['bitrate'] == 256 and j['extension'] == 'm4a'" GET /api/settings
expect "step 6: PUT /api/settings MP3 320" 200 "j['format'] == 'mp3' and j['extension'] == 'mp3'" \
    PUT /api/settings '{"format": "mp3", "bitrate": 320}'
expect "step 6: MP3 256 isn't offered" 422 "j['error']['code'] == 'validation_failed'" \
    PUT /api/settings '{"format": "mp3", "bitrate": 256}'
expect "step 6: PUT /api/settings back to AAC 256" 200 "j['extension'] == 'm4a'" \
    PUT /api/settings '{"format": "aac", "bitrate": 256}'
# Settings › Container, and the API's own 404.
expect "GET /api/container: image $image_version, spytifyd $spytify_version" 200 \
    "j['device_name'] == 'spotivault-smoke' and j['versions']['image'] == '$image_version' and '$spytify_version' in j['versions']['spytify']" \
    GET /api/container
expect "GET /api/nope: the not_found envelope" 404 "j['error']['code'] == 'not_found'" GET /api/nope

step "6. spytifyd and the shim"
v="$(in_app spytifyd --version || true)"
if [[ "$v" == "spytifyd v$spytify_version "* ]]; then pass "$v"; else fail "spytifyd --version: '$v'"; fi
h="$(in_app sh -c 'LD_PRELOAD=/usr/local/lib/hostname-shim.so hostname')"
if [ "$h" = spotivault-smoke ]; then pass "the shim reports DEVICE_NAME as the hostname"; else fail "hostname with the shim: '$h'"; fi

step "7. fake recordings with the image's ffmpeg"
docker cp "$here/fake-timeline.json" "$name:/tmp/fake-timeline.json"
for fmt in aac mp3 flac; do
    out="/tmp/rec-$fmt"
    if ! in_app sh -c "mkdir -p $out/run && cd $out/run && spytifyd --once --fake /tmp/fake-timeline.json \
        --idle-exit 3s --wait-target 10s --log-file $out/spytifyd.log \
        --set output.dir=$out/music --set encode.format=$fmt --set encode.bitrate_kbps=256 \
        --set privacy.bug_tracker=false >$out/stdout.log 2>&1"; then
        fail "$fmt: spytifyd exited with an error"
        in_app sh -c "tail -n 20 $out/stdout.log $out/spytifyd.log" || true
        continue
    fi
    files="$(in_app sh -c "find $out/music -type f ! -path '*/.spytify/*' | sort")"
    count="$(grep -c . <<<"$files" || true)"
    ext="$(case $fmt in aac) echo m4a ;; *) echo "$fmt" ;; esac)"
    if [ "$count" = 2 ] && ! grep -qv "\.$ext\$" <<<"$files"; then
        decoded=1
        while IFS= read -r f; do
            in_app ffmpeg -v error -nostdin -i "$f" -f null - || decoded=0
        done <<<"$files"
        if [ "$decoded" = 1 ]; then pass "$fmt: 2 .$ext files that decode"; else fail "$fmt: a file doesn't decode"; fi
    else
        fail "$fmt: expected 2 .$ext files, got: $(tr '\n' ' ' <<<"$files")"
        in_app sh -c "tail -n 20 $out/spytifyd.log" || true
    fi
done

step "8. bad settings stop the container"
i=0
for env in "TZ=Nowhere/Bogus" "UMASK=999" "DEVICE_NAME=a/b"; do
    i=$((i + 1))
    if out="$(timeout 60 docker run --rm --name "$name-bad$i" -e "$env" "$image" 2>&1)"; then
        fail "$env: the container ran"
    elif grep -q "init: " <<<"$out"; then
        pass "$env: $(grep -m1 'init: ' <<<"$out" | sed 's/.*init: //')"
    else
        fail "$env: stopped without the init message"
    fi
done

if [ "$install" = 1 ]; then
    step "9. the controller installs the client, then s6 starts it"
    # The watcher started with the container: it saw the hello, started the install unless the
    # controller already had, and collects the client.install events until the end (it gives up
    # after 600 s by itself).
    if wait "$watcher"; then watched=0; else watched=$?; fi
    watcher=""
    summary="$(tail -n 1 "$tmp/install-events.json")"
    sed 's/^/        /' "$tmp/install-events.json"
    printf '%s\n' "$summary" >"$tmp/body"
    if [ "$watched" = 0 ]; then
        pass "WS /api/events: $(json "'%d client.install events, phases %s, %d with download progress, %s in %s s' % (j['events'], '/'.join(j['phases']), j['download_events'], j['final_state'], j['elapsed_s'])")"
    else
        fail "WS /api/events during the install: ${summary:-no output}"
    fi
    version="$(json "j['version']")"
    expect "GET /api/client/status: installed, version $version" 200 \
        "j['installed'] is True and j['version'] == '$version' and j['install']['state'] == 'installed'" \
        GET /api/client/status
    # spotify-install itself, as app: the controller's install left nothing for it to do.
    t0="$(date +%s)"
    out="$(in_app spotify-install || true)"
    grep -v '"stage":"download","message":"Downloading' <<<"$out" | sed 's/^/        /'
    if tail -n 1 <<<"$out" | grep -q '"stage":"done"'; then
        pass "spotify-install reports the client installed ($(($(date +%s) - t0)) s)"
    else
        fail "spotify-install"
    fi
    pid=""
    for _ in $(seq 1 30); do
        pid="$(client_pid)"
        [ -n "$pid" ] && break
        sleep 2
    done
    if [ -n "$pid" ]; then
        pass "the client runs (pid $pid)"
        if in_app grep -q hostname-shim.so "/proc/$pid/maps"; then pass "the shim is loaded"; else fail "the shim isn't loaded"; fi
        uid="$(in_app awk '/^Uid:/ {print $2}' "/proc/$pid/status")"
        if [ "$uid" = 1000 ]; then pass "the client runs as app"; else fail "the client runs as uid $uid"; fi
    else
        fail "the client didn't start"
    fi
    expect "GET /api/health: the client is running" 200 "j['checks']['client'] == 'running'" GET /api/health
    # Login detection on the real client (web-ui.md step 3): its window is found, and a fresh
    # /config isn't logged in. The login screen's window is titled plain "Spotify".
    for _ in $(seq 1 30); do
        api GET /api/client/status
        [ "$(json "j['running'] and j['login_signals']['window_title'] is not None")" = True ] && break
        sleep 2
    done
    expect "GET /api/client/status: the client's window is seen, not logged in" 200 \
        "j['running'] and j['login_signals']['window_title'] == 'Spotify' and j['logged_in'] is False" \
        GET /api/client/status
    # Restart client (step 3's Reset login screen): MPRIS Quit, then s6 starts it again. The old
    # main process must be gone and a new one running; a helper's pid changing proves nothing.
    expect "POST /api/client/restart" 202 "j['restartable'] is True" POST /api/client/restart
    if [ -n "$pid" ]; then
        new_pid=""
        old_gone=0
        for _ in $(seq 1 30); do
            if in_app test -d "/proc/$pid"; then old_gone=0; else old_gone=1; fi
            new_pid="$(client_pid)"
            [ "$old_gone" = 1 ] && [ -n "$new_pid" ] && [ "$new_pid" != "$pid" ] && break
            sleep 2
        done
        if [ "$old_gone" = 1 ] && [ -n "$new_pid" ] && [ "$new_pid" != "$pid" ]; then
            pass "the client restarted (main pid $pid, then $new_pid)"
        else
            fail "the client didn't restart (main pid $pid $([ "$old_gone" = 1 ] && echo gone || echo "still running"), now ${new_pid:-none})"
        fi
        # It quit by itself, over MPRIS: the controller didn't have to kill it.
        restart_log="$(docker logs "$name" 2>&1 | grep 'restart: ' || true)"
        if grep -qi 'kill' <<<"$restart_log"; then
            fail "the client was killed, not quit: $(tr '\n' ' ' <<<"$restart_log")"
        elif grep -q 'asked the client to quit' <<<"$restart_log"; then
            pass "it quit over MPRIS, without SIGKILL"
        else
            fail "no restart in the controller's log"
        fi
    fi
    # The client ignores SIGTERM; its service quits it over MPRIS. Without that, a stop waits out
    # every grace period.
    sleep 10
    t0="$(date +%s)"
    docker stop -t 60 "$name" >/dev/null
    took=$(($(date +%s) - t0))
    if [ "$took" -le 20 ]; then pass "docker stop took ${took} s"; else fail "docker stop took ${took} s"; fi
fi

step "10. init writes /config as app: a link app planted there leaves root's files alone"
# Any app process can swap a file in /config for a link. At the next start, init-spotivault's
# writes there (its own log, the machine ID) go through app, so a link to one of root's files
# must leave that file as it was, and root's.
if [ "$(docker inspect -f '{{.State.Running}}' "$name")" != true ]; then docker start "$name" >/dev/null; fi
root_files=(/etc/passwd /etc/group /etc/shadow)
before="$(docker exec "$name" sha256sum "${root_files[@]}")"
in_app sh -c 'ln -sfn /etc/passwd /config/logs/init/current && ln -sfn /etc/shadow /config/logs/init/current.new &&
    ln -sfn /etc/group /config/machine-id'
docker restart -t 60 "$name" >/dev/null
status=""
for _ in $(seq 1 90); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$name" 2>/dev/null || echo gone)"
    [ "$status" = healthy ] || [ "$status" = gone ] && break
    sleep 2
done
if [ "$status" = healthy ]; then pass "healthy again after the restart"; else fail "health is '$status' after the restart"; fi
owners="$(docker exec "$name" stat -c %U "${root_files[@]}" | sort -u)"
if [ "$(docker exec "$name" sha256sum "${root_files[@]}")" = "$before" ] && [ "$owners" = root ]; then
    pass "/etc/passwd, /etc/group and /etc/shadow unchanged, and root's"
else
    fail "a root file changed through a link in /config (owners: $(tr '\n' ' ' <<<"$owners"))"
fi
if in_app test ! -L /config/logs/init/current && in_app grep -q 'DEVICE_NAME=' /config/logs/init/current; then
    pass "init's log is a file again, with this start's lines"
else
    fail "init's log: still a link, or no lines from this start"
fi
if in_app test ! -L /config/machine-id && in_app grep -Eqx '[0-9a-f]{32}' /config/machine-id; then
    pass "a new machine ID, in a file"
else
    fail "/config/machine-id: still a link, or no machine ID"
fi

step "size"
# The sum of the layers, uncompressed. (docker image inspect's .Size is the compressed size on
# Docker Desktop's containerd store.) The controller is the layer with its Python runtime and the
# one with its venv.
layers="$(docker history --no-trunc --format '{{.Size}}\t{{.CreatedBy}}' "$image" | awk -F '\t' '
    function mb(v) { n = v + 0; if (v ~ /GB$/) return n * 1000; if (v ~ /MB$/) return n; if (v ~ /kB$/) return n / 1000; return n / 1e6 }
    { total += mb($1) }
    index($2, "install -y --no-install-recommends python3") || index($2, "/opt/spotivault/venv") { controller += mb($1) }
    END { printf "%.0f %.0f", total, controller }')"
report="$(printf '### Image size\n\n%s: **%s MB** uncompressed, of which the controller (Python and its venv) is %s MB\n\n```\n%s\n```\n' \
    "$image" "${layers% *}" "${layers#* }" \
    "$(docker history --format '{{.Size}}\t{{.CreatedBy}}' "$image" | cut -c1-140)")"
echo "$report"
[ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "$report" >> "$GITHUB_STEP_SUMMARY"

echo
if [ "$failed" = 0 ]; then echo "smoke test passed"; else echo "smoke test FAILED"; exit 1; fi
