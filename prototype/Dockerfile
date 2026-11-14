# Feasibility prototype: NOT the production image.
# Bakes in the Spotify client and uses supervisord for speed of iteration.

# Build the DEVICE_NAME hostname shim (see hostname-shim.c).
FROM ubuntu:24.04 AS shim
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY hostname-shim.c /src/
RUN gcc -O2 -Wall -shared -fPIC -o /src/hostname-shim.so /src/hostname-shim.c -ldl

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg procps util-linux \
        xvfb openbox x11vnc novnc websockify fonts-dejavu-core \
        dbus dbus-x11 pulseaudio pulseaudio-utils libasound2-plugins \
        supervisor python3 xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Spotify client from Spotify's own apt repo (signing key 5384CE82BA52C83A, binary keyring).
RUN curl -fsSL -o /usr/share/keyrings/spotify.gpg \
        https://download.spotify.com/debian/pubkey_5384CE82BA52C83A.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/spotify.gpg] http://repository.spotify.com stable non-free" \
        > /etc/apt/sources.list.d/spotify.list \
    && apt-get update && apt-get install -y --no-install-recommends spotify-client \
    && rm -rf /var/lib/apt/lists/*

# Spytify 2.0 (recorder daemon + CLI). Pulls in ffmpeg and Mesa.
ARG SPYTIFY_VERSION=2.0.1
RUN curl -fsSL -o /tmp/spytify.deb \
        "https://github.com/spytify/spytify/releases/download/${SPYTIFY_VERSION}/spytify_${SPYTIFY_VERSION}_amd64.deb" \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/spytify.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/spytify.deb

RUN dbus-uuidgen > /etc/machine-id \
    && userdel --remove ubuntu \
    && useradd --uid 1000 --home-dir /config/home --no-create-home --shell /bin/bash app \
    && printf 'pcm.!default pulse\nctl.!default pulse\n' > /etc/asound.conf

COPY pulse.pa /etc/pulse/spotivault.pa
COPY supervisord.conf /etc/supervisor/spotivault.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY probe.py /usr/local/bin/probe
COPY --from=shim /src/hostname-shim.so /usr/local/lib/hostname-shim.so
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/probe

# One session environment shared by every process (and by `docker exec -u app`).
ENV HOME=/config/home \
    DISPLAY=:99 \
    XDG_RUNTIME_DIR=/tmp/runtime-app \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/runtime-app/bus \
    PULSE_SERVER=unix:/tmp/runtime-app/pulse/native \
    SPYTIFY_TARGET_PROCESS=spotify \
    SPYTIFY_TARGET_MPRIS=org.mpris.MediaPlayer2.spotify \
    SPYTIFY_SOCKET=/tmp/runtime-app/spytify.sock \
    PROBE_STATE=/config/probe \
    DEVICE_NAME=spotivault \
    TZ=UTC

VOLUME ["/config", "/music"]
EXPOSE 6080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
