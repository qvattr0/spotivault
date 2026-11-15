#!/usr/bin/env bash
# shellcheck disable=SC2016 # single-quoted scripts run inside the container
# Container smoke test, run by CI and by hand:
#
#   image/test/smoke.sh IMAGE [--install]
#
# Starts IMAGE as a fresh container with no volumes mapped, then checks:
#   1. it turns healthy;
#   2. only s6's supervision tree (started by /init) runs as root;
#   3. WS /vnc reaches the VNC server (RFB 003.008);
#   4. spytifyd reports the pinned version, and the DEVICE_NAME shim works;
#   5. spytifyd --fake records AAC, MP3 and FLAC with the image's ffmpeg;
#   6. bad settings stop the container with a clear message;
#   7. with --install: spotify-install installs the client, s6 starts it with the shim loaded,
#      and a stop with the client running is quick.
# Prints a size report at the end, and appends it to $GITHUB_STEP_SUMMARY when set.
set -euo pipefail

image="${1:?usage: smoke.sh IMAGE [--install]}"
install=0
[ "${2:-}" = --install ] && install=1
here="$(cd "$(dirname "$0")" && pwd)"
name="spotivault-smoke-$$"
port="${SMOKE_PORT:-18080}"
spytify_version="${SPYTIFY_VERSION:-2.0.2}"
failed=0

pass() { printf '  ok    %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; failed=1; }
step() { printf '\n== %s\n' "$*"; }
in_app() { docker exec -u app "$name" "$@"; }

cleanup() {
    if [ "$failed" = 1 ]; then
        echo; echo "--- container log (last 80 lines)"; docker logs --tail 80 "$name" 2>&1 || true
    fi
    docker rm -fv "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

step "start $image"
docker run -d --name "$name" --shm-size 1g -p "127.0.0.1:$port:8080" \
    -e DEVICE_NAME=spotivault-smoke "$image" >/dev/null

step "1. health"
status=""
for _ in $(seq 1 90); do
    status="$(docker inspect -f '{{.State.Health.Status}}' "$name" 2>/dev/null || echo gone)"
    [ "$status" = healthy ] || [ "$status" = gone ] && break
    sleep 2
done
if [ "$status" = healthy ]; then pass "healthy"; else fail "health is '$status'"; exit 1; fi
curl -fsS "http://127.0.0.1:$port/api/health" && echo

step "2. only s6 (from /init) runs as root"
# Read /proc as app, so the check itself isn't a root process.
procs="$(in_app sh -c 'for d in /proc/[0-9]*; do
    u=$(awk "/^Uid:/ {print \$2}" "$d/status" 2>/dev/null) || continue
    [ -n "$u" ] && printf "%s %s %s\n" "$u" "${d#/proc/}" "$(cat "$d/comm" 2>/dev/null)"
done')"
root="$(awk '$1 == 0 {print $3}' <<<"$procs" | sort | uniq -c)"
while read -r line; do echo "        root: $line"; done <<<"$root"
bad="$(awk '$1 == 0 && $3 !~ /^s6-(svscan|supervise|linux-init-s|fdholderd|ipcserverd)$/ {print $2 "/" $3}' <<<"$procs")"
if [ -z "$bad" ]; then pass "every other process runs as app"; else fail "root processes outside s6: $bad"; fi
for svc in Xvfb x11vnc matchbox-window pulseaudio dbus-daemon spotivault-cont; do
    if awk -v s="$svc" '$1 == 1000 && index($3, s) == 1 {found = 1} END {exit !found}' <<<"$procs"; then
        pass "$svc runs as app"
    else
        fail "$svc isn't running as app"
    fi
done

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

step "4. spytifyd and the shim"
v="$(in_app spytifyd --version || true)"
if [[ "$v" == "spytifyd v$spytify_version "* ]]; then pass "$v"; else fail "spytifyd --version: '$v'"; fi
h="$(in_app sh -c 'LD_PRELOAD=/usr/local/lib/hostname-shim.so hostname')"
if [ "$h" = spotivault-smoke ]; then pass "the shim reports DEVICE_NAME as the hostname"; else fail "hostname with the shim: '$h'"; fi

step "5. fake recordings with the image's ffmpeg"
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

step "6. bad settings stop the container"
for env in "TZ=Nowhere/Bogus" "UMASK=999" "DEVICE_NAME=a/b"; do
    if out="$(timeout 60 docker run --rm -e "$env" "$image" 2>&1)"; then
        fail "$env: the container ran"
    elif grep -q "init: " <<<"$out"; then
        pass "$env: $(grep -m1 'init: ' <<<"$out" | sed 's/.*init: //')"
    else
        fail "$env: stopped without the init message"
    fi
done

if [ "$install" = 1 ]; then
    step "7. spotify-install, then s6 starts the client"
    t0="$(date +%s)"
    out="$(in_app spotify-install || true)"
    grep -v '"stage":"download","message":"Downloading' <<<"$out" | sed 's/^/        /'
    if tail -n 1 <<<"$out" | grep -q '"stage":"done"'; then
        pass "spotify-install in $(($(date +%s) - t0)) s"
    else
        fail "spotify-install"
    fi
    pid=""
    for _ in $(seq 1 30); do
        pid="$(in_app sh -c 'for d in /proc/[0-9]*; do [ "$(cat $d/comm 2>/dev/null)" = spotify ] && { echo ${d#/proc/}; break; }; done' || true)"
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
    # The client ignores SIGTERM; its service quits it over MPRIS. Without that, a stop waits out
    # every grace period.
    sleep 10
    t0="$(date +%s)"
    docker stop -t 60 "$name" >/dev/null
    took=$(($(date +%s) - t0))
    if [ "$took" -le 20 ]; then pass "docker stop took ${took} s"; else fail "docker stop took ${took} s"; fi
fi

step "size"
# The sum of the layers, uncompressed. (docker image inspect's .Size is the compressed size on
# Docker Desktop's containerd store.) The last layer is the stub controller, which S4 replaces.
layers="$(docker history --format '{{.Size}}' "$image" | awk '
    function mb(v) { n = v + 0; if (v ~ /GB$/) return n * 1000; if (v ~ /MB$/) return n; if (v ~ /kB$/) return n / 1000; return n / 1e6 }
    NR == 1 { stub = mb($1) } { total += mb($1) } END { printf "%.0f %.0f", total, total - stub }')"
report="$(printf '### Image size\n\n%s: **%s MB** uncompressed, %s MB without the stub controller\n\n```\n%s\n```\n' \
    "$image" "${layers% *}" "${layers#* }" \
    "$(docker history --format '{{.Size}}\t{{.CreatedBy}}' "$image" | cut -c1-140)")"
echo "$report"
[ -n "${GITHUB_STEP_SUMMARY:-}" ] && echo "$report" >> "$GITHUB_STEP_SUMMARY"

echo
if [ "$failed" = 0 ]; then echo "smoke test passed"; else echo "smoke test FAILED"; exit 1; fi
