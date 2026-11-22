# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv
# (It flags SPOTIFY_KEY_*: that's Spotify's public repository key, not a secret.)
#
# spotivault: one image with the Spotify client's screen, sound and libraries, the Spytify
# recorder and the controller. The Spotify client itself isn't in the image: spotify-install puts
# it in /config at runtime. See docs/design.md § Container.
#
#   docker build -t spotivault:dev .
#   docker build --build-arg IMAGE_VERSION=0.1.0 -t spotivault:0.1.0 .

ARG UBUNTU=ubuntu:24.04
ARG GOLANG=golang:1.26.11-trixie
# uv builds the controller's venv from controller/uv.lock. Keep it at the version that wrote the
# lock file (a newer lock format fails with --frozen on an older uv).
ARG UV=ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa
# Node builds the web UI (web/) once, in its own stage; only web/dist leaves it. Node 22.18 is the
# floor web/package.json asks for. Pinned by digest, like uv.
ARG NODE=node:22.18.0-trixie-slim@sha256:d02467efc049791a7586a20e36d9219d184ab89e45b19c57e88cff322678c233

FROM ${UV} AS uv

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

# --- noVNC's core, for the controller's web root ------------------------------------------------
# The controller serves files from SPOTIVAULT_WEB_ROOT (/usr/local/share/spotivault/web). Its own
# /vnc.html page (controller/src/spotivault/web/static/) imports novnc/core/rfb.js from there.
FROM cbuild AS web
ARG NOVNC_VERSION=1.7.0
ARG NOVNC_SHA256=32689f18d6abe96bc6530828a6bd0b9ae33bda07c083a6575ed255b5a8f2e903
RUN curl -fsSL -o /tmp/novnc.tgz "https://registry.npmjs.org/@novnc/novnc/-/novnc-$NOVNC_VERSION.tgz" \
    && echo "$NOVNC_SHA256  /tmp/novnc.tgz" | sha256sum -c \
    && mkdir -p /out/novnc \
    && tar -C /out/novnc --strip-components=1 -xzf /tmp/novnc.tgz --wildcards \
         'package/core' 'package/vendor' 'package/LICENSE.txt' 'package/docs/LICENSE.*' \
    && chmod -R a+rX,go-w /out

# --- The web UI: npm ci and vite build, in a pinned Node -----------------------------------------
# web/dist is the built React app (S7). The UI imports the logo from docs/brand (the @brand/ alias),
# so that folder goes in beside web/. node_modules, the design drawings and test output stay out of
# the context (.dockerignore).
FROM ${NODE} AS webui
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
COPY docs/brand/ /src/docs/brand/
RUN npm run build

# --- The controller: a venv with the locked dependencies, byte-compiled -----------------------
# Built on the same Ubuntu Python the image runs. The venv's python links to /usr/bin/python3.12,
# which the final stage installs too. Only /opt/spotivault/venv leaves this stage: no uv, no pip,
# no caches, no sources but the installed package.
FROM ${UBUNTU} AS controller
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON=/usr/bin/python3.12 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/spotivault/venv \
    UV_FROZEN=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy
WORKDIR /src/controller
# The dependencies first, in their own cached step: they change less often than the code.
COPY controller/pyproject.toml controller/uv.lock ./
RUN uv sync --no-dev --no-install-project
# Then the package itself, as a wheel (not a link back to /src). pyproject.toml's readme is
# ARCHITECTURE.md, so the build needs it.
COPY controller/ARCHITECTURE.md ./
COPY controller/src/ src/
# Byte-compiled here, because the app user can't write to /opt/spotivault. Timestamp pycs: COPY
# keeps the files' mtimes, so they stay valid in the final stage (smoke.sh checks it).
RUN uv sync --no-dev --no-editable \
    && venv=/opt/spotivault/venv \
    && test ! -e "$venv/bin/pip" \
    && find "$venv" -name '*.pyc' -delete \
    && "$venv/bin/python" -m compileall -q -j 0 "$venv/lib/python3.12/site-packages" \
    && "$venv/bin/python" -c 'import spotivault.app, spotivault.__main__' \
    && test -f "$venv/lib/python3.12/site-packages/spotivault/store/migrations/001_initial.sql"

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

# The controller's runtime, in its own layer:
#   python3    Ubuntu's Python 3.12 (docs/design.md § Stack). Not python3-minimal: that lacks
#              asyncio and sqlite3.
#   x11-utils  xwininfo, which reads the client's window title for login detection (web-ui.md step 3).
RUN set -eux \
    && apt-get update \
    && apt-get install -y --no-install-recommends python3 x11-utils \
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

# Last, as they change most: noVNC's core in the web root, the controller's venv, and the built UI
# (index.html and its hashed assets, beside novnc/). s6 runs /opt/spotivault/venv/bin/python -m
# spotivault (image/rootfs/etc/s6-overlay/s6-rc.d/controller).
COPY --from=web /out/ /usr/local/share/spotivault/web/
COPY --from=controller /opt/spotivault/venv/ /opt/spotivault/venv/
COPY --from=webui /src/web/dist/ /usr/local/share/spotivault/web/
# The image's version, for Settings › Container (GET /api/container).
ARG IMAGE_VERSION=dev
ENV SPOTIVAULT_IMAGE_VERSION=$IMAGE_VERSION
