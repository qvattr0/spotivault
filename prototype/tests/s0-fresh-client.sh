#!/bin/sh
# S0 (M1 plan): three checks in one, without touching the logged-in client.
#
# 1. Q13: install the Spotify client at runtime, the way spotivault will: verify Spotify's
#    InRelease with gpgv, check Packages and the .deb by sha256, dpkg-deb -x into a folder.
#    Each phase is timed.
# 2. Q2: start that copy with an empty profile on its own X display and D-Bus bus, and read
#    the signals a logged-out client gives (MPRIS name, Users folder, window title). The same
#    signals are read from the logged-in client for comparison.
# 3. --disable-dev-shm-usage: does the fresh copy keep out of /dev/shm with the flag?
#
# Run inside the prototype container as `app`:
#   docker exec -u app spotivault-prototype sh /config/s0/s0-fresh-client.sh
set -u
DEST=${DEST:-/config/s0/spotify}
WORK=$(mktemp -d /tmp/s0.XXXXXX)
REPO=${SPOTIFY_REPO:-https://repository.spotify.com}
KEYRING=${KEYRING:-/usr/share/keyrings/spotify.gpg}
mkdir -p "$DEST"
now() { date +%s.%N; }
lap() { awk -v a="$1" -v b="$(now)" 'BEGIN { printf "%.1f s", b - a }'; }

echo "== Q13: runtime install"
t0=$(now)
curl -fsSL "$REPO/dists/stable/InRelease" -o "$WORK/InRelease"
if gpgv --keyring "$KEYRING" "$WORK/InRelease" >"$WORK/gpgv.log" 2>&1; then
  echo "InRelease: signature OK ($(lap "$t0"))"
else
  echo "InRelease: signature FAILED"; cat "$WORK/gpgv.log"; exit 1
fi
want=$(awk '/^SHA256:/{s=1;next} /^[A-Za-z]/{s=0} s && $3=="non-free/binary-amd64/Packages"{print $1}' "$WORK/InRelease")
t1=$(now)
curl -fsSL "$REPO/dists/stable/non-free/binary-amd64/Packages" -o "$WORK/Packages"
got=$(sha256sum "$WORK/Packages" | cut -d' ' -f1)
[ "$want" = "$got" ] && echo "Packages: sha256 OK ($(lap "$t1"))" || { echo "Packages: sha256 MISMATCH"; exit 1; }
# The newest spotify-client stanza (the file lists one per version).
awk 'BEGIN{RS=""} /(^|\n)Package: spotify-client\n/' "$WORK/Packages" >"$WORK/stanzas"
ver=$(grep '^Version:' "$WORK/stanzas" | cut -d' ' -f2 | sort -V | tail -1)
stanza=$(awk -v v="$ver" 'BEGIN{RS="";ORS="\n\n"} $0 ~ "Version: " v "\n" {print}' "$WORK/stanzas")
file=$(printf '%s\n' "$stanza" | awk '/^Filename:/{print $2}')
sha=$(printf '%s\n' "$stanza" | awk '/^SHA256:/{print $2}')
size=$(printf '%s\n' "$stanza" | awk '/^Size:/{print $2}')
echo "Newest client: $ver, $size bytes"
t2=$(now)
curl -fsSL "$REPO/$file" -o "$WORK/client.deb"
echo "Download: $(lap "$t2")"
t3=$(now)
[ "$(sha256sum "$WORK/client.deb" | cut -d' ' -f1)" = "$sha" ] && echo ".deb: sha256 OK ($(lap "$t3"))" || { echo ".deb: sha256 MISMATCH"; exit 1; }
t4=$(now)
dir="$DEST/versions/$ver"
rm -rf "$dir.tmp" && mkdir -p "$dir.tmp" && dpkg-deb -x "$WORK/client.deb" "$dir.tmp" && rm -rf "$dir" && mv "$dir.tmp" "$dir"
echo "Unpack: $(lap "$t4"), $(du -sh "$dir" | cut -f1) on disk"
bin="$dir/usr/share/spotify/spotify"
missing=$(ldd "$bin" 2>&1 | grep 'not found' || true)
[ -z "$missing" ] && echo "ldd: no missing libraries" || { echo "ldd: MISSING"; echo "$missing"; }
echo "Total install time: $(lap "$t0")"
rm -f "$WORK/client.deb"

echo
echo "== Q2: logged-out signals (fresh profile on :98)"
export HOME="$WORK/home" DISPLAY=:98 DBUS_SESSION_BUS_ADDRESS="unix:path=$WORK/bus"
mkdir -p "$HOME"
Xvfb :98 -screen 0 1280x800x24 -nolisten tcp >"$WORK/xvfb.log" 2>&1 &
xpid=$!
dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --nofork --nopidfile >"$WORK/dbus.log" 2>&1 &
dpid=$!
sleep 2
"$bin" --no-zygote --no-sandbox --disable-gpu --disable-dev-shm-usage >"$WORK/spotify.log" 2>&1 &
spid=$!
sleep "${WAIT:-30}"
mpris=$(dbus-send --session --print-reply --dest=org.freedesktop.DBus / org.freedesktop.DBus.ListNames 2>/dev/null | grep -o 'org.mpris.MediaPlayer2[^"]*' || true)
echo "MPRIS name on the bus: ${mpris:-none}"
if [ -n "$mpris" ]; then
  st=$(dbus-send --session --print-reply --dest=org.mpris.MediaPlayer2.spotify /org/mpris/MediaPlayer2 \
       org.freedesktop.DBus.Properties.Get string:org.mpris.MediaPlayer2.Player string:PlaybackStatus 2>&1 | grep -o '"[A-Za-z]*"' | tail -1)
  md=$(dbus-send --session --print-reply --dest=org.mpris.MediaPlayer2.spotify /org/mpris/MediaPlayer2 \
       org.freedesktop.DBus.Properties.Get string:org.mpris.MediaPlayer2.Player string:Metadata 2>&1 | grep -c 'dict entry' || true)
  echo "  PlaybackStatus=$st, metadata entries=$md"
fi
echo "Users folder: $(ls "$HOME/.config/spotify/Users" 2>/dev/null | sed 's/^[^-]*-user$/<id>-user/' | tr '\n' ' ' || true)$( [ -d "$HOME/.config/spotify/Users" ] || echo absent)"
echo "Window titles: $(xwininfo -root -tree 2>/dev/null | grep -o '"[^"]*[Ss]potify[^"]*"' | sort -u | tr '\n' ' ')"
# /dev/shm: count the fresh copy's open files there (its processes run from $dir).
shm=0
for p in $(pgrep -f "$dir/usr/share/spotify" || true); do
  n=$(ls -l "/proc/$p/fd" 2>/dev/null | grep -c '/dev/shm/' || true)
  shm=$((shm + n))
done
echo "--disable-dev-shm-usage: open /dev/shm files in the fresh copy = $shm"
kill "$spid" 2>/dev/null; sleep 2; pkill -f "$dir/usr/share/spotify" 2>/dev/null; kill "$dpid" "$xpid" 2>/dev/null

echo
echo "== Q2: the logged-in client (:99, main bus) for comparison"
export HOME=/config/home DISPLAY=:99 DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/runtime-app/bus
mpris=$(dbus-send --session --print-reply --dest=org.freedesktop.DBus / org.freedesktop.DBus.ListNames 2>/dev/null | grep -o 'org.mpris.MediaPlayer2[^"]*' || true)
echo "MPRIS name on the bus: ${mpris:-none}"
echo "Users folder: $(ls "$HOME/.config/spotify/Users" 2>/dev/null | sed 's/^[^-]*-user$/<id>-user/' | tr '\n' ' ')"
echo "Window titles: $(xwininfo -root -tree 2>/dev/null | grep -o '"[^"]*[Ss]potify[^"]*"' | sort -u | tr '\n' ' ')"
shm=0
for p in $(pgrep -x spotify || true); do
  n=$(ls -l "/proc/$p/fd" 2>/dev/null | grep -c '/dev/shm/' || true)
  shm=$((shm + n))
done
echo "Without the flag: open /dev/shm files in the logged-in client = $shm ($(du -sh /dev/shm | cut -f1) used in /dev/shm)"
rm -rf "$WORK"
