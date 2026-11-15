# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv
# (It flags SPOTIFY_KEY_*: that's Spotify's public repository key, not a secret.)
#
# spotivault: one image with the Spotify client's screen, sound and libraries, the Spytify
# recorder and the controller. The Spotify client itself isn't in the image: spotify-install puts
# it in /config at runtime. See docs/design.md § Container.
#
#   docker build -t spotivault:dev .

ARG UBUNTU=ubuntu:24.04
ARG GOLANG=golang:1.26.11-trixie

# --- Spytify source, at a pinned tag, with our local patches ----------------------------------
FROM ${GOLANG} AS spytify-src
ARG SPYTIFY_VERSION=2.0.2
ARG SPYTIFY_COMMIT=fef3f4e0af3b4909462080e713c269b0f123f7d1
RUN git clone --quiet --depth 1 --branch "$SPYTIFY_VERSION" https://github.com/spytify/spytify.git /src/spytify \
    && test "$(git -C /src/spytify rev-parse HEAD)" = "$SPYTIFY_COMMIT"
COPY image/spytify/patches/ /src/patches/
RUN cd /src/spytify \
    && for p in /src/patches/*.patch; do \
         [ -e "$p" ] || continue; echo "applying $p"; git apply "$p"; \
       done

# --- spytifyd: a static Go binary (the .deb would pull Mesa, GL and X for the desktop app) ----
FROM spytify-src AS spytifyd
ARG SPYTIFY_VERSION=2.0.2
RUN cd /src/spytify \
    && CGO_ENABLED=0 go build -trimpath -o /out/spytifyd \
         -ldflags "-s -w -X github.com/spytify/spytify/pkg/proto.Version=v$SPYTIFY_VERSION -X github.com/spytify/spytify/internal/telemetry.DSN=" \
         ./cmd/spytifyd \
    && ! ldd /out/spytifyd

# --- C toolchain for ffmpeg and the shim -------------------------------------------------------
FROM ${UBUNTU} AS cbuild
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gcc libc6-dev make nasm xz-utils \
    && rm -rf /var/lib/apt/lists/*

# --- ffmpeg with only what Spytify runs it for, by Spytify's own recipe -----------------------
FROM cbuild AS ffmpeg
COPY --from=spytify-src /src/spytify/scripts/ /src/spytify/scripts/
RUN /src/spytify/scripts/build-ffmpeg.sh /out

# --- The DEVICE_NAME hostname shim -------------------------------------------------------------
FROM cbuild AS shim
COPY image/hostname-shim.c /src/
RUN mkdir /out && gcc -O2 -Wall -shared -fPIC -o /out/hostname-shim.so /src/hostname-shim.c -ldl

# --- s6-overlay v3 -----------------------------------------------------------------------------
FROM cbuild AS s6
ARG S6_OVERLAY_VERSION=3.2.3.2
ARG S6_NOARCH_SHA256=5379750ed30a84bbd2e2dd74847ba6b5bd29cd0b2e3ea2ec58049b57eb2eda12
ARG S6_X86_64_SHA256=e6befcc96a437a3831386ecfc51808c5d3e939dc5fe3c02ae9284599e8aa2408
RUN cd /tmp \
    && base="https://github.com/just-containers/s6-overlay/releases/download/v$S6_OVERLAY_VERSION" \
    && curl -fsSLO "$base/s6-overlay-noarch.tar.xz" -fsSLO "$base/s6-overlay-x86_64.tar.xz" \
    && echo "$S6_NOARCH_SHA256  s6-overlay-noarch.tar.xz" | sha256sum -c \
    && echo "$S6_X86_64_SHA256  s6-overlay-x86_64.tar.xz" | sha256sum -c \
    && mkdir /out \
    && tar -C /out -Jxpf s6-overlay-noarch.tar.xz \
    && tar -C /out -Jxpf s6-overlay-x86_64.tar.xz

# --- Stub controller (throwaway, replaced in S4), with noVNC's core bundled in -----------------
FROM ${GOLANG} AS stub
ARG NOVNC_VERSION=1.7.0
ARG NOVNC_SHA256=32689f18d6abe96bc6530828a6bd0b9ae33bda07c083a6575ed255b5a8f2e903
WORKDIR /src
COPY image/stub/go.mod image/stub/go.sum ./
RUN go mod download
COPY image/stub/ ./
RUN curl -fsSL -o /tmp/novnc.tgz "https://registry.npmjs.org/@novnc/novnc/-/novnc-$NOVNC_VERSION.tgz" \
    && echo "$NOVNC_SHA256  /tmp/novnc.tgz" | sha256sum -c \
    && mkdir -p web/novnc \
    && tar -C web/novnc --strip-components=1 -xzf /tmp/novnc.tgz --wildcards \
         'package/core' 'package/vendor' 'package/LICENSE.txt' 'package/docs/LICENSE.*' \
    && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/spotivault-controller .

# --- Placeholder packages for hard Depends that nothing here loads ----------------------------
# Empty packages that stand in for real ones, so apt doesn't pull what no program here links:
#   libasound2-plugins  pulseaudio Depends on it. ALSA's plugins pull libavcodec and its codecs
#                       (about 97 MB). The client talks to PulseAudio directly through libpulse.
#   tk                  x11vnc Depends on it for its optional -gui (Tcl/Tk, about 10 MB).
FROM ${UBUNTU} AS placeholders
RUN set -eu; mkdir /out; \
    for p in libasound2-plugins tk; do \
      mkdir -p "/tmp/$p/DEBIAN"; \
      printf 'Package: %s\nVersion: 99:0+spotivault\nArchitecture: amd64\nMaintainer: spotivault\nDescription: placeholder: nothing in spotivault loads %s\n' "$p" "$p" \
        > "/tmp/$p/DEBIAN/control"; \
      dpkg-deb --build --root-owner-group "/tmp/$p" "/out/$p.deb"; \
    done

# --- The image ---------------------------------------------------------------------------------
FROM ${UBUNTU}
ARG DEBIAN_FRONTEND=noninteractive
# Spotify's repository signing key, kept in the image to check InRelease at runtime.
ARG SPOTIFY_KEY_URL=https://download.spotify.com/debian/pubkey_5384CE82BA52C83A.gpg
ARG SPOTIFY_KEY_SHA256=31cc40faddd0e0ffb62fb53a04e4ad79c7fc0945b8c1622233c480571be34572

COPY image/rootfs/etc/dpkg/ /etc/dpkg/
COPY --from=placeholders /out/ /tmp/placeholders/

# The client's libraries without the client: install spotify-client so apt resolves its Depends
# (--no-install-recommends keeps out the libavcodec it only uses for local files), keep what it
# pulled in, then purge the client. dbus-x11 stands in for dbus-user-session, which would pull
# systemd. See the dpkg excludes for the files left out (Mesa's drivers among them).
RUN set -eux \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL -o /usr/share/keyrings/spotify.gpg "$SPOTIFY_KEY_URL" \
    && echo "$SPOTIFY_KEY_SHA256  /usr/share/keyrings/spotify.gpg" | sha256sum -c \
    && echo "deb [signed-by=/usr/share/keyrings/spotify.gpg] https://repository.spotify.com stable non-free" \
         > /etc/apt/sources.list.d/spotify.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
         /tmp/placeholders/*.deb \
         spotify-client \
         xvfb x11vnc matchbox-window-manager \
         dbus-daemon dbus-x11 \
         pulseaudio pulseaudio-utils \
         tzdata \
    && apt-get purge -y spotify-client \
    && keep="$(apt-get -s autoremove | awk '/^Remv /{print $2}')" \
    && echo "keeping the client's dependencies: $keep" \
    && apt-mark manual $keep \
    && test -z "$(apt-get -s autoremove | awk '/^Remv /{print $2}')" \
    && rm -r /etc/apt/sources.list.d/spotify.list /tmp/placeholders \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/debconf/*-old /var/lib/dpkg/*-old /var/log/apt /var/log/dpkg.log

# The app user (uid 1000) replaces the base image's "ubuntu" user. /config/home is its home.
# /etc/machine-id follows /config/machine-id, which init-spotivault keeps for the life of /config.
RUN userdel --remove ubuntu \
    && useradd --uid 1000 --user-group --home-dir /config/home --no-create-home --shell /usr/sbin/nologin app \
    && ln -sf /config/machine-id /etc/machine-id \
    && mkdir -p /var/lib/dbus && ln -sf /config/machine-id /var/lib/dbus/machine-id

COPY --from=s6 /out/ /
COPY --from=ffmpeg /out/ffmpeg /usr/local/bin/ffmpeg
COPY --from=spytifyd /out/spytifyd /usr/local/bin/spytifyd
COPY --from=shim /out/hostname-shim.so /usr/local/lib/hostname-shim.so
COPY image/rootfs/ /

ENV PATH=/command:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/config/home \
    DISPLAY=:99 \
    XDG_RUNTIME_DIR=/tmp/runtime-app \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/runtime-app/bus \
    PULSE_SERVER=unix:/tmp/runtime-app/pulse/native \
    SPYTIFY_TARGET_PROCESS=spotify \
    SPYTIFY_TARGET_MPRIS=org.mpris.MediaPlayer2.spotify \
    SPYTIFY_FFMPEG=/usr/local/bin/ffmpeg \
    SPYTIFY_CONFIG=/config/spytify/config.toml \
    DEVICE_NAME=spotivault \
    TZ=UTC \
    UMASK=000 \
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=60000 \
    S6_SERVICES_GRACETIME=50000 \
    S6_KILL_GRACETIME=3000 \
    S6_VERBOSITY=1

VOLUME ["/config", "/music"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --start-interval=2s --retries=3 \
    CMD curl -fsS -o /dev/null http://127.0.0.1:8080/api/health || exit 1
ENTRYPOINT ["/init"]

# Last, in its own layer: the stub controller. S4 replaces it with the real one.
COPY --from=stub /out/spotivault-controller /usr/local/bin/spotivault-controller
