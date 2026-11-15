"""The controller's settings from the environment (docs/design.md § Container, § Configuration).

`load_config()` reads them once at start-up. Nothing else reads `os.environ`. Tests and local
development pass their own mapping instead of the real environment.

The container's own variables, set in the UGOS Docker app:

| Variable | Default | Meaning |
|---|---|---|
| `TZ` | `UTC` | Time zone for the schedule. |
| `UMASK` | `000` | 3 or 4 octal digits. Applies to `/music` only (set on the recorder). |
| `DEVICE_NAME` | `spotivault` | The Spotify Connect device name. |
| `UI_PASSWORD` | unset | Not enforced in M1 (plan D11): only reported and logged. |

The controller's own variables, all optional (documented in controller/ARCHITECTURE.md):

| Variable | Default | Meaning |
|---|---|---|
| `SPOTIVAULT_FAKE` | `0` | `1`: fake mode, a simulated player, recorder, client and Web API. |
| `SPOTIVAULT_HOST` | `0.0.0.0` | Address to listen on. |
| `SPOTIVAULT_PORT` | `8080` | Port to listen on. |
| `SPOTIVAULT_CONFIG_DIR` | `/config` (fake: `./.dev/config`) | The config volume. |
| `SPOTIVAULT_MUSIC_DIR` | `/music` (fake: `./.dev/music`) | The music volume. |
| `SPOTIVAULT_WEB_ROOT` | `/usr/local/share/spotivault/web` | The built web UI. |
| `SPOTIVAULT_LOG_LEVEL` | `INFO` | Python logging level. |
| `SPOTIVAULT_IMAGE_VERSION` | `dev` | The image's version, set when the image is built. |
| `SPOTIVAULT_VNC` | `127.0.0.1:5900` | The VNC server that `WS /vnc` bridges to. |
| `SPOTIVAULT_ALLOWED_HOSTS` | empty | More names the UI may be reached by (web/guard.py). |
| `SPOTIVAULT_FAKE_SCENARIO` | `demo` | Fake mode's start: `fresh`, `demo` or `wizard`. |
| `SPOTIVAULT_FAKE_SPEED` | `1` | Fake mode's clock runs this many times faster. |

Read as the image sets them: `XDG_RUNTIME_DIR`, `DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`,
`PULSE_SERVER`, `SPYTIFY_TARGET_MPRIS`, `SPYTIFY_FFMPEG` and `SPYTIFY_CONFIG`.
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}
FAKE_SCENARIOS = ("fresh", "demo", "wizard")  # fake/world.py describes each


class ConfigError(ValueError):
    """A setting in the environment is wrong. The message says which and how to fix it."""


@dataclass(frozen=True, slots=True)
class Config:
    """Every setting the controller reads from its environment. Immutable once loaded."""

    tz: str
    umask: str  # as given, for GET /api/container: "000" or "0022"
    device_name: str
    ui_password: str | None = field(repr=False)
    fake: bool
    host: str
    port: int
    config_dir: Path
    music_dir: Path
    web_root: Path
    log_level: str
    image_version: str
    runtime_dir: Path  # XDG_RUNTIME_DIR: recorder sockets live here
    display: str
    dbus_address: str  # the session bus, for MPRIS
    pulse_server: str
    mpris_name: str  # the client's MPRIS bus name
    ffmpeg_path: Path
    spytify_config: Path
    vnc_host: str
    vnc_port: int
    # SPOTIVAULT_ALLOWED_HOSTS: names, lowercased, the controller answers to besides the ones
    # web/guard.py always allows (an IP address, `nas`, `nas.local`, …).
    allowed_hosts: tuple[str, ...] = ()
    spytifyd_path: Path = Path("/usr/local/bin/spytifyd")
    spotify_install_path: Path = Path("/usr/local/bin/spotify-install")
    fake_scenario: str | None = None  # None: fake/__init__.py picks by the clock
    fake_speed: float = 1.0

    @property
    def umask_bits(self) -> int:
        """UMASK as a number, for os.umask (the recorder's, never /config's)."""
        return int(self.umask, 8)

    @property
    def zone(self) -> ZoneInfo:
        """The schedule's time zone."""
        return ZoneInfo(self.tz)

    @property
    def ui_password_set(self) -> bool:
        return bool(self.ui_password)

    @property
    def db_path(self) -> Path:
        """The SQLite database: /config/db/spotivault.db."""
        return self.config_dir / "db" / "spotivault.db"

    @property
    def logs_dir(self) -> Path:
        """s6-log writes each service's log here: /config/logs/<service>/current."""
        return self.config_dir / "logs"

    @property
    def spytify_logs_dir(self) -> Path:
        """Per-item recorder logs and event files: /config/logs/spytify/<run>-<item>.*"""
        return self.logs_dir / "spytify"

    @property
    def home_dir(self) -> Path:
        """The app user's HOME, where the client keeps its login and prefs."""
        return self.config_dir / "home"

    @property
    def spotify_dir(self) -> Path:
        """Where spotify-install puts the client: /config/spotify/current/spotify."""
        return self.config_dir / "spotify"

    @property
    def covers_cache_dir(self) -> Path:
        """300 px cover thumbnails (design.md § Playlist covers)."""
        return self.config_dir / "cache" / "covers"

    @property
    def spytify_index(self) -> Path:
        """Spytify's duplicate index, in the music folder."""
        return self.music_dir / ".spytify" / "recorded.jsonl"


def load_config(env: Mapping[str, str] | None = None, *, fake: bool | None = None) -> Config:
    """Reads and checks the settings. `env` defaults to os.environ; `fake` overrides
    SPOTIVAULT_FAKE.

    Raises ConfigError with a message for the log when a setting is wrong. The rules for TZ,
    UMASK and DEVICE_NAME are the ones init-spotivault checks before the controller starts.
    """
    if env is None:
        env = os.environ
    is_fake = _flag(env, "SPOTIVAULT_FAKE") if fake is None else fake

    tz = env.get("TZ") or "UTC"
    _check_tz(tz)
    umask = env.get("UMASK", "000")
    if not re.fullmatch(r"[0-7]{3,4}", umask):
        raise ConfigError(f"UMASK must be 3 or 4 octal digits, such as 000 or 022 (got {umask!r})")
    device_name = env.get("DEVICE_NAME", "spotivault")
    _check_device_name(device_name)

    dev_root = Path.cwd() / ".dev"
    default_config = dev_root / "config" if is_fake else Path("/config")
    default_music = dev_root / "music" if is_fake else Path("/music")
    config_dir = _path(env, "SPOTIVAULT_CONFIG_DIR", default_config)
    runtime_dir = _path(env, "XDG_RUNTIME_DIR", Path("/tmp/runtime-app"))
    vnc_host, vnc_port = _host_port(env.get("SPOTIVAULT_VNC", "127.0.0.1:5900"), "SPOTIVAULT_VNC")
    fake_scenario = env.get("SPOTIVAULT_FAKE_SCENARIO") or None
    if fake_scenario is not None and fake_scenario not in FAKE_SCENARIOS:
        raise ConfigError(
            f"SPOTIVAULT_FAKE_SCENARIO must be fresh, demo or wizard (got {fake_scenario!r})"
        )

    return Config(
        tz=tz,
        umask=umask,
        device_name=device_name,
        ui_password=env.get("UI_PASSWORD") or None,
        fake=is_fake,
        host=env.get("SPOTIVAULT_HOST", "0.0.0.0"),
        port=_port(env.get("SPOTIVAULT_PORT", "8080"), "SPOTIVAULT_PORT"),
        config_dir=config_dir,
        music_dir=_path(env, "SPOTIVAULT_MUSIC_DIR", default_music),
        web_root=_path(env, "SPOTIVAULT_WEB_ROOT", Path("/usr/local/share/spotivault/web")),
        log_level=_log_level(env.get("SPOTIVAULT_LOG_LEVEL", "INFO")),
        image_version=env.get("SPOTIVAULT_IMAGE_VERSION", "dev"),
        runtime_dir=runtime_dir,
        display=env.get("DISPLAY", ":99"),
        dbus_address=env.get("DBUS_SESSION_BUS_ADDRESS") or f"unix:path={runtime_dir / 'bus'}",
        pulse_server=env.get("PULSE_SERVER", f"unix:{runtime_dir}/pulse/native"),
        mpris_name=env.get("SPYTIFY_TARGET_MPRIS", "org.mpris.MediaPlayer2.spotify"),
        ffmpeg_path=_path(env, "SPYTIFY_FFMPEG", Path("/usr/local/bin/ffmpeg")),
        spytify_config=_path(env, "SPYTIFY_CONFIG", config_dir / "spytify" / "config.toml"),
        vnc_host=vnc_host,
        vnc_port=vnc_port,
        allowed_hosts=_host_names(env.get("SPOTIVAULT_ALLOWED_HOSTS", "")),
        fake_scenario=fake_scenario,
        fake_speed=_speed(env.get("SPOTIVAULT_FAKE_SPEED", "1")),
    )


def _flag(env: Mapping[str, str], name: str) -> bool:
    value = env.get(name, "").strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{name} must be 1 or 0 (got {value!r})")


def _path(env: Mapping[str, str], name: str, default: Path) -> Path:
    value = env.get(name)
    if not value:
        return default
    path = Path(value)
    if not path.is_absolute():
        raise ConfigError(f"{name} must be an absolute path (got {value!r})")
    return path


def _port(value: str, name: str) -> int:
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise ConfigError(f"{name} must be a port number from 1 to 65535 (got {value!r})")
    return int(value)


def _host_port(value: str, name: str) -> tuple[str, int]:
    host, sep, port = value.rpartition(":")
    if not sep or not host:
        raise ConfigError(f"{name} must be host:port, such as 127.0.0.1:5900 (got {value!r})")
    return host, _port(port, name)


def _host_names(value: str) -> tuple[str, ...]:
    """SPOTIVAULT_ALLOWED_HOSTS: host names separated by commas, without a scheme or port."""
    names = []
    for item in value.split(","):
        name = item.strip().lower().rstrip(".")
        if not name:
            continue
        if not re.fullmatch(r"[a-z0-9_-]+(\.[a-z0-9_-]+)*", name):
            raise ConfigError(
                "SPOTIVAULT_ALLOWED_HOSTS must be host names separated by commas, such as "
                f"nas.example.com, with no scheme or port (got {item.strip()!r})"
            )
        names.append(name)
    return tuple(names)


def _speed(value: str) -> float:
    try:
        speed = float(value)
    except ValueError:
        speed = 0.0
    if not 0 < speed <= 1000:
        raise ConfigError(
            f"SPOTIVAULT_FAKE_SPEED must be a number above 0, such as 1 or 10 (got {value!r})"
        )
    return speed


def _log_level(value: str) -> str:
    level = value.strip().upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ConfigError(
            f"SPOTIVAULT_LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR (got {value!r})"
        )
    return level


def _check_tz(tz: str) -> None:
    if tz.startswith("/") or ".." in tz:
        raise ConfigError(f"TZ must be a time zone name, such as Europe/Berlin (got {tz!r})")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"TZ: unknown time zone {tz!r}") from exc


def _check_device_name(name: str) -> None:
    # It becomes the client's hostname (the DEVICE_NAME shim), so it must fit in one.
    if not name:
        raise ConfigError("DEVICE_NAME is empty")
    if len(name.encode("utf-8")) > 64:
        raise ConfigError("DEVICE_NAME is longer than 64 bytes")
    if "/" in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ConfigError("DEVICE_NAME can't contain '/' or control characters")
