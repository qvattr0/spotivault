#!/bin/sh
# Runs as root: prepare folders, then drop to the unprivileged "app" user for everything else.
set -eu

mkdir -p /config/home /config/logs /config/probe /music "$XDG_RUNTIME_DIR/pulse"
chown app:app /config /config/home /config/logs /config/probe "$XDG_RUNTIME_DIR" "$XDG_RUNTIME_DIR/pulse"
chown app:app /music 2>/dev/null || echo "note: cannot chown /music; relying on the folder's own permissions"
chmod 0700 "$XDG_RUNTIME_DIR"

# Keep one machine ID for the life of /config, not per image build: the Spotify client's saved
# login appears to be tied to it.
[ -s /config/machine-id ] || dbus-uuidgen > /config/machine-id
cp /config/machine-id /etc/machine-id

# Chromium (inside the Spotify client) locks its profile to "<hostname>-<pid>". A lock left by an
# earlier container, or one with another hostname, makes the client quit at once. Nothing can be
# running yet, so clear them.
rm -f /config/home/.cache/spotify/Singleton*

exec setpriv --reuid=app --regid=app --init-groups \
    /usr/bin/supervisord -n -c /etc/supervisor/spotivault.conf
