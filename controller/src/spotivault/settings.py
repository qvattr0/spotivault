"""Settings: the saved settings, the file layout's rules, and their mapping to Spytify's `--set`.

- **GET/PUT /api/settings** (routers/settings.py): `SettingsService.get()` and `update()`. Each
  setting is one row of the `settings` table, its value as JSON (contracts/schema.sql). A setting
  that was never saved has no row and reads as its default, so a row means "chosen".
- **The layout** (Settings › Files › Layout, web-ui.md § Files): `check_layout()` applies the rules
  of contracts/vectors/layouts.json in their order, and `layout_to_spytify()` maps a valid layout
  to Spytify's `output.*` settings (plan D2, Q16).
- **The recorder's settings** (plan § Starting Spytify for an item): the run engine (S6) calls
  `await services.settings.recorder_settings(mode)` when each item starts, and passes every pair
  as `--set key=value`. So a change saved during a run applies from the next item.

Other modules can react to a save with `add_listener()`; wizard step 7 uses it (setup.py).
"""

import json
import logging
import re
import sqlite3
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import ValidationError

from spotivault.api.models import Layout, Settings, SettingsUpdate
from spotivault.clock import iso_ms
from spotivault.errors import ApiError, validation_failed

if TYPE_CHECKING:
    from spotivault.services import Services

log = logging.getLogger(__name__)

DEFAULT_PATTERN = "{album_artist}/{album}/{track} - {title}"

# Every key the settings table holds, with its default (contracts/schema.sql § settings).
# The first six are the API's Settings; run_order (S6) and webapi_burst_threshold (S5) are read
# and written with get_value() and set_value().
DEFAULTS: dict[str, Any] = {
    "format": "aac",
    "bitrate": 256,
    "write_m3u": True,
    "save_spotify_covers": True,
    "auto_track_owned": True,
    "layout": {
        "pattern": DEFAULT_PATTERN,
        "prefix": "none",
        "underscores": False,
        "strip_accents": False,
    },
    "run_order": ["carried_over", "liked", "playlists", "albums"],
    "webapi_burst_threshold": 30,
}

# The format and bitrate pairs Settings › Recording offers (openapi.yaml Settings.bitrate).
OFFERED_FORMATS: dict[str, tuple[int | None, ...]] = {
    "aac": (256, 320),
    "mp3": (320,),
    "flac": (None,),
    "wav": (None,),
}

EXTENSIONS = {"aac": "m4a", "mp3": "mp3", "flac": "flac", "wav": "wav"}

_BOOLEAN_KEYS = ("write_m3u", "save_spotify_covers", "auto_track_owned")

type SettingsListener = Callable[[frozenset[str]], Awaitable[None]]


# --- The layout --------------------------------------------------------------------------------

# The six placeholders the Edit layout modal offers (web-ui.md § Files).
PLACEHOLDERS = ("album_artist", "artists", "title", "album", "track", "year")
# Spytify needs one of these in the file name; {year} doesn't count, it's always empty on Linux.
NAMING_PLACEHOLDERS = ("album_artist", "artists", "title", "album", "track")
# The folder part, before the last "/", and Spytify's output.group_by for it.
FOLDERS = {"{album_artist}": "artist", "{album_artist}/{album}": "artist/album"}
# The modal's Prefix option, and Spytify's output.prefix for it.
PREFIXES = {"none": "none", "counter": "counter", "track_number": "album_track"}

_BRACED = re.compile(r"\{[^{}]*\}")
# C0 control characters and DEL. A NUL can't go into a `--set` argument at all.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

type LayoutReason = Literal[
    "unknown_placeholder",
    "stray_brace",
    "backslash",
    "control_character",
    "bad_folder",
    "empty_file_name",
    "no_placeholder",
]


@dataclass(frozen=True, slots=True)
class LayoutProblem:
    """Why a layout is refused: one of layouts.json's reasons, and an English message."""

    reason: LayoutReason
    message: str
    placeholder: str | None = None  # the unknown one, for unknown_placeholder

    def details(self) -> dict[str, Any]:
        """The error envelope's `details` (openapi.yaml putSettings 422)."""
        details: dict[str, Any] = {"reason": self.reason}
        if self.placeholder is not None:
            details["placeholder"] = self.placeholder
        return details

    def error(self) -> ApiError:
        return ApiError(422, "invalid_layout", self.message, self.details())


def check_layout(pattern: str) -> LayoutProblem | None:
    """The first rule `pattern` breaks, or None when it's valid.

    The rules and their order are contracts/vectors/layouts.json's: web-ui.md § Files lists
    unknown_placeholder, bad_folder and empty_file_name; stray_brace, backslash,
    control_character and no_placeholder are the contract's extra rules. Spytify would refuse a
    backslash and no placeholder at the start of every item, and a NUL can't even be passed to it.
    """
    for braced in _BRACED.findall(pattern):
        if braced[1:-1] not in PLACEHOLDERS:
            return LayoutProblem(
                "unknown_placeholder", f"{braced} is not a placeholder.", placeholder=braced
            )
    unbraced = _BRACED.sub("", pattern)
    if "{" in unbraced or "}" in unbraced:
        return LayoutProblem("stray_brace", "A { or } isn't part of a placeholder.")
    if "\\" in pattern:
        return LayoutProblem("backslash", "The layout can't contain a backslash.")
    if _CONTROL.search(pattern):
        return LayoutProblem(
            "control_character", "The layout can't contain a control character, such as a tab."
        )
    folder, slash, name = pattern.rpartition("/")
    if slash and folder not in FOLDERS:
        return LayoutProblem(
            "bad_folder", "The folder part must be none, {album_artist} or {album_artist}/{album}."
        )
    if not name.strip():
        return LayoutProblem("empty_file_name", "The file name, after the last /, is empty.")
    if not any(braced[1:-1] in NAMING_PLACEHOLDERS for braced in _BRACED.findall(name)):
        return LayoutProblem(
            "no_placeholder", "The file name needs a placeholder other than {year}."
        )
    return None


def layout_to_spytify(layout: Layout) -> dict[str, str | bool]:
    """Spytify's output settings for a valid layout (layouts.json "Mapping").

    output.template is the file name unchanged: Spytify trims the name it builds itself.
    """
    folder, slash, name = layout.pattern.rpartition("/")
    return {
        "output.group_by": FOLDERS[folder] if slash else "none",
        "output.template": name,
        "output.prefix": PREFIXES[layout.prefix],
        "output.underscores": layout.underscores,
        "output.ascii_filenames": layout.strip_accents,
    }


# --- The recorder's settings -------------------------------------------------------------------

# How an item is played (design.md § Run flow): only its missing tracks (albums, Liked Songs,
# playlists you own or collaborate on), or whole (followed and linked playlists).
type PlayMode = Literal["missing_only", "whole"]


def build_recorder_settings(
    settings: Settings, *, music_dir: Path, mode: PlayMode
) -> list[tuple[str, str]]:
    """Every `--set key=value` for one spytifyd process, in a stable order.

    plan § Starting Spytify for an item, and design.md § Container's Spytify defaults:
    - output.dir, encode.format and encode.bitrate_kbps are always explicit, because Spytify's
      default is MP3 160. FLAC and WAV have no bitrate, so it's left out for them.
    - the layout's five output.* settings;
    - recorder.skip_duplicates_forward is off for missing-tracks-only items and on for whole ones;
    - fixed values: duplicates skipped, no stop with the player, medium covers in the tags, no
      bug tracker, and no playlist file from Spytify (the controller writes the .m3u itself).
    Booleans are "true" or "false", as Spytify takes them.
    """
    pairs: list[tuple[str, str]] = [
        ("output.dir", str(music_dir)),
        ("encode.format", settings.format),
    ]
    if settings.bitrate is not None:
        pairs.append(("encode.bitrate_kbps", str(settings.bitrate)))
    for key, value in layout_to_spytify(settings.layout).items():
        pairs.append((key, _setting_text(value)))
    pairs += [
        ("output.playlist", "false"),
        ("recorder.duplicates", "skip"),
        ("recorder.skip_duplicates_forward", _setting_text(mode == "whole")),
        ("recorder.stop_with_player", "false"),
        ("tags.cover_size", "medium"),
        ("privacy.bug_tracker", "false"),
    ]
    return pairs


def _setting_text(value: str | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


# --- The service -------------------------------------------------------------------------------


class SettingsService:
    """The saved settings. Built by services.py as `services.settings`."""

    def __init__(self, services: "Services") -> None:
        self.services = services
        self._listeners: list[SettingsListener] = []

    def add_listener(self, listener: SettingsListener) -> None:
        """`listener(keys)` is awaited after each save that changed `keys`, once it's committed.
        An error in a listener is logged; the save stands."""
        self._listeners.append(listener)

    async def get(self) -> Settings:
        """The saved settings, with defaults for those never saved (GET /api/settings)."""
        values = await self._read(DEFAULTS.keys())
        format_, bitrate = values["format"], values["bitrate"]
        if bitrate not in OFFERED_FORMATS[format_]:
            log.warning(
                "settings: %s at %s kbps isn't offered; using the default", format_, bitrate
            )
            format_, bitrate = DEFAULTS["format"], DEFAULTS["bitrate"]
        return Settings(
            format=format_,
            bitrate=bitrate,
            extension=EXTENSIONS[format_],
            write_m3u=values["write_m3u"],
            save_spotify_covers=values["save_spotify_covers"],
            auto_track_owned=values["auto_track_owned"],
            layout=Layout.model_validate(values["layout"]),
        )

    async def update(self, change: SettingsUpdate) -> Settings:
        """Saves the fields `change` carries; the others keep their value (PUT /api/settings).

        Raises ApiError 422: `validation_failed` (no field, a null where null isn't allowed, or a
        format and bitrate that aren't offered together) or `invalid_layout`.
        """
        given = set(change.model_fields_set)
        if not given:
            raise validation_failed("body", "Send at least one setting.")
        for name in sorted(given - {"bitrate"}):
            if getattr(change, name) is None:
                raise validation_failed(name, f"{name} can't be null.")
        if ("format" in given) != ("bitrate" in given):
            missing = "bitrate" if "format" in given else "format"
            raise validation_failed(missing, "format and bitrate go together.")
        if "format" in given:
            assert change.format is not None
            if change.bitrate not in OFFERED_FORMATS[change.format]:
                at = "no bitrate" if change.bitrate is None else f"{change.bitrate} kbps"
                raise validation_failed("bitrate", f"{change.format} isn't offered at {at}.")
        if change.layout is not None:
            problem = check_layout(change.layout.pattern)
            if problem is not None:
                raise problem.error()

        values = {name: _to_json(getattr(change, name)) for name in given}
        await self._write(values)
        log.info("settings: saved %s", ", ".join(sorted(given)))
        await self._notify(frozenset(given))
        return await self.get()

    async def get_value(self, key: str) -> Any:
        """One setting as its JSON value, or its default: for `run_order` (S6) and
        `webapi_burst_threshold` (S5), which aren't in the API's Settings."""
        return (await self._read([key]))[key]

    async def set_value(self, key: str, value: Any) -> None:
        """Saves one setting. The caller checks the value; `key` must be in DEFAULTS. Listeners
        are told, as for a PUT."""
        if key not in DEFAULTS:
            raise KeyError(f"no setting {key!r}")
        await self._write({key: value})
        await self._notify(frozenset({key}))

    async def recorder_settings(self, mode: PlayMode) -> list[tuple[str, str]]:
        """The `--set` pairs for the item about to start, from the settings saved now.

        The run engine (S6) calls this as each item starts and passes the result in
        `ports.RecorderSpec.settings`. `mode` is how the item is played: "missing_only" or "whole".
        """
        settings = await self.get()
        return build_recorder_settings(
            settings, music_dir=self.services.config.music_dir, mode=mode
        )

    # --- Storage --------------------------------------------------------------------------------

    async def _read(self, keys: Iterable[str]) -> dict[str, Any]:
        """The given settings: the saved value when it's there and sane, else the default."""
        wanted = list(keys)
        rows = await self.services.store.fetchall(
            f"SELECT key, value FROM settings WHERE key IN ({', '.join('?' * len(wanted))})",
            wanted,
        )
        saved = {row["key"]: row["value"] for row in rows}
        values: dict[str, Any] = {}
        for key in wanted:
            default = DEFAULTS.get(key)
            if key not in saved:
                values[key] = default
                continue
            try:
                value = json.loads(saved[key])
            except ValueError:
                value = None
            if _sane(key, value):
                values[key] = value
            else:
                log.warning("settings: the saved %s is invalid (%r); using the default", key, value)
                values[key] = default
        return values

    async def _write(self, values: dict[str, Any]) -> None:
        now = iso_ms(self.services.clock.now())
        rows = [(key, json.dumps(value), now) for key, value in sorted(values.items())]

        def write(conn: sqlite3.Connection) -> None:
            conn.executemany(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                rows,
            )

        await self.services.store.transaction(write)

    async def _notify(self, keys: frozenset[str]) -> None:
        for listener in self._listeners:
            try:
                await listener(keys)
            except Exception:
                log.exception("settings: a listener failed after saving %s", ", ".join(keys))


def _to_json(value: Any) -> Any:
    """A SettingsUpdate field as the JSON value stored for it."""
    if isinstance(value, Layout):
        return value.model_dump(mode="json")
    return value


def _sane(key: str, value: Any) -> bool:
    """Whether a value read from the database can be used. A stored value always passed the
    API's checks, so this only catches a database edited by hand."""
    if key == "format":
        return value in OFFERED_FORMATS
    if key == "bitrate":
        return value in (256, 320, None)
    if key in _BOOLEAN_KEYS:
        return isinstance(value, bool)
    if key == "layout":
        try:
            layout = Layout.model_validate(value)
        except ValidationError:
            return False
        return check_layout(layout.pattern) is None
    if key == "run_order":
        return isinstance(value, list) and all(isinstance(group, str) for group in value)
    if key == "webapi_burst_threshold":
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    return True
