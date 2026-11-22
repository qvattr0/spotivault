"""GET/PUT /api/settings and the recorder's `--set` list (owner: settings-storage-setup)."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from contract import assert_response, openapi
from spotivault.api.models import Layout, Settings
from spotivault.services import Services
from spotivault.settings import DEFAULT_PATTERN, build_recorder_settings

PUT_EXAMPLES = openapi()["paths"]["/api/settings"]["put"]["requestBody"]["content"][
    "application/json"
]["examples"]
DEFAULT_EXAMPLE = openapi()["components"]["examples"]["SettingsDefault"]["value"]
INVALID_LAYOUT_EXAMPLE = openapi()["paths"]["/api/settings"]["put"]["responses"]["422"]["content"][
    "application/json"
]["examples"]["unknownPlaceholder"]["value"]


async def test_defaults_are_the_contract_example(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/settings")
    assert response.status_code == 200
    assert_response(response, "/api/settings")
    assert response.json() == DEFAULT_EXAMPLE


@pytest.mark.parametrize("name", sorted(PUT_EXAMPLES))
async def test_the_contract_put_examples_are_saved(client: httpx.AsyncClient, name: str) -> None:
    body = PUT_EXAMPLES[name]["value"]
    response = await client.put("/api/settings", json=body)
    assert response.status_code == 200
    assert_response(response, "/api/settings")
    saved = response.json()
    for key, value in body.items():
        assert saved[key] == value
    assert (await client.get("/api/settings")).json() == saved


async def test_fields_left_out_keep_their_value(client: httpx.AsyncClient) -> None:
    await client.put("/api/settings", json={"format": "mp3", "bitrate": 320})
    await client.put("/api/settings", json={"write_m3u": False})
    saved = (await client.get("/api/settings")).json()
    assert (saved["format"], saved["bitrate"], saved["extension"]) == ("mp3", 320, "mp3")
    assert saved["write_m3u"] is False
    assert saved["save_spotify_covers"] is True


@pytest.mark.parametrize(
    ("format_", "bitrate", "extension"),
    [
        ("aac", 256, "m4a"),
        ("aac", 320, "m4a"),
        ("mp3", 320, "mp3"),
        ("flac", None, "flac"),
        ("wav", None, "wav"),
    ],
)
async def test_every_offered_format(
    client: httpx.AsyncClient, format_: str, bitrate: int | None, extension: str
) -> None:
    response = await client.put("/api/settings", json={"format": format_, "bitrate": bitrate})
    assert response.status_code == 200
    body = response.json()
    assert (body["format"], body["bitrate"], body["extension"]) == (format_, bitrate, extension)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "body"),
        ({"format": "aac"}, "bitrate"),
        ({"bitrate": 320}, "format"),
        ({"format": "mp3", "bitrate": 256}, "bitrate"),
        ({"format": "aac", "bitrate": None}, "bitrate"),
        ({"format": "flac", "bitrate": 320}, "bitrate"),
        ({"format": None, "bitrate": 256}, "format"),
        ({"write_m3u": None}, "write_m3u"),
        ({"layout": None}, "layout"),
        ({"format": "ogg", "bitrate": 320}, "format"),
        ({"bitrate": 160, "format": "aac"}, "bitrate"),
        (
            {
                "layout": {
                    "pattern": "{title}" * 30,  # over maxLength 200
                    "prefix": "none",
                    "underscores": False,
                    "strip_accents": False,
                }
            },
            "layout.pattern",
        ),
        ({"extension": "m4a"}, "extension"),
    ],
)
async def test_invalid_bodies_are_validation_failed(
    client: httpx.AsyncClient, body: dict[str, Any], field: str
) -> None:
    before = (await client.get("/api/settings")).json()
    response = await client.put("/api/settings", json=body)
    assert response.status_code == 422
    assert_response(response, "/api/settings")
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["details"]["field"] == field
    assert (await client.get("/api/settings")).json() == before


async def test_an_invalid_layout_is_the_contract_example(client: httpx.AsyncClient) -> None:
    layout = {"pattern": "{album_artist}/{genre}", "prefix": "none", "underscores": False}
    response = await client.put(
        "/api/settings", json={"layout": {**layout, "strip_accents": False}}
    )
    assert response.status_code == 422
    assert_response(response, "/api/settings")
    assert response.json() == INVALID_LAYOUT_EXAMPLE


async def test_settings_are_stored_one_json_row_each(
    client: httpx.AsyncClient, services: Services
) -> None:
    await client.put("/api/settings", json={"auto_track_owned": False})
    rows = await services.store.fetchall("SELECT key, value, updated_at FROM settings")
    assert [(row["key"], json.loads(row["value"])) for row in rows] == [("auto_track_owned", False)]
    assert rows[0]["updated_at"] == "2026-11-15T00:00:00.000Z"  # the fake clock's start


async def test_a_value_edited_by_hand_falls_back_to_its_default(
    client: httpx.AsyncClient, services: Services, caplog: pytest.LogCaptureFixture
) -> None:
    bad = {"pattern": "{genre}", "prefix": "none", "underscores": False, "strip_accents": False}
    rows = [("layout", json.dumps(bad)), ("write_m3u", '"yes"'), ("format", '"mp3"')]
    for key, value in rows:
        await services.store.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, 'x')", (key, value)
        )
    settings = (await client.get("/api/settings")).json()
    assert settings["layout"]["pattern"] == DEFAULT_PATTERN
    assert settings["write_m3u"] is True
    # mp3 with the default bitrate (256) isn't offered: both go back to the default.
    assert (settings["format"], settings["bitrate"]) == ("aac", 256)
    assert "the saved layout is invalid" in caplog.text


async def test_listeners_hear_each_save_after_it(
    client: httpx.AsyncClient, services: Services
) -> None:
    heard: list[tuple[frozenset[str], bool]] = []

    async def listener(keys: frozenset[str]) -> None:
        saved = await services.settings.get()
        heard.append((keys, saved.write_m3u))

    async def broken(keys: frozenset[str]) -> None:
        raise RuntimeError("boom")

    services.settings.add_listener(broken)
    services.settings.add_listener(listener)
    response = await client.put("/api/settings", json={"write_m3u": False})
    assert response.status_code == 200  # a failing listener doesn't undo the save
    assert heard == [(frozenset({"write_m3u"}), False)]


async def test_values_outside_the_api(running_app: object, services: Services) -> None:
    assert await services.settings.get_value("run_order") == [
        "carried_over",
        "liked",
        "playlists",
        "albums",
    ]
    assert await services.settings.get_value("webapi_burst_threshold") == 30
    await services.settings.set_value("run_order", ["albums", "playlists", "liked"])
    assert await services.settings.get_value("run_order") == ["albums", "playlists", "liked"]
    with pytest.raises(KeyError):
        await services.settings.set_value("nope", 1)


# --- The recorder's settings -------------------------------------------------------------------


def _settings(**changes: Any) -> Settings:
    return Settings.model_validate({**DEFAULT_EXAMPLE, **changes})


def test_recorder_settings_for_the_defaults() -> None:
    pairs = build_recorder_settings(_settings(), music_dir=Path("/music"), mode="missing_only")
    assert pairs == [
        ("output.dir", "/music"),
        ("encode.format", "aac"),
        ("encode.bitrate_kbps", "256"),
        ("output.group_by", "artist/album"),
        ("output.template", "{track} - {title}"),
        ("output.prefix", "none"),
        ("output.underscores", "false"),
        ("output.ascii_filenames", "false"),
        ("output.playlist", "false"),
        ("recorder.duplicates", "skip"),
        ("recorder.skip_duplicates_forward", "false"),
        ("recorder.stop_with_player", "false"),
        ("tags.cover_size", "medium"),
        ("privacy.bug_tracker", "false"),
    ]


def test_items_played_whole_skip_duplicates_forward() -> None:
    pairs = dict(build_recorder_settings(_settings(), music_dir=Path("/music"), mode="whole"))
    assert pairs["recorder.skip_duplicates_forward"] == "true"


def test_lossless_formats_have_no_bitrate() -> None:
    flac = _settings(format="flac", bitrate=None, extension="flac")
    pairs = dict(build_recorder_settings(flac, music_dir=Path("/music"), mode="missing_only"))
    assert pairs["encode.format"] == "flac"
    assert "encode.bitrate_kbps" not in pairs


def test_the_layout_options_map_to_spytify() -> None:
    layout = Layout(
        pattern="{artists} - {title}", prefix="counter", underscores=True, strip_accents=True
    )
    pairs = dict(
        build_recorder_settings(_settings(layout=layout), music_dir=Path("/m"), mode="whole")
    )
    assert pairs["output.group_by"] == "none"
    assert pairs["output.template"] == "{artists} - {title}"
    assert pairs["output.prefix"] == "counter"
    assert pairs["output.underscores"] == "true"
    assert pairs["output.ascii_filenames"] == "true"


async def test_a_saved_change_reaches_the_next_items_settings(
    client: httpx.AsyncClient, services: Services
) -> None:
    await client.put("/api/settings", json={"format": "mp3", "bitrate": 320})
    got = dict(await services.settings.recorder_settings("missing_only"))
    assert (got["encode.format"], got["encode.bitrate_kbps"]) == ("mp3", "320")
    assert got["output.dir"] == str(services.config.music_dir)
