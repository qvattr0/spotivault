"""webapi/endpoints.py: the allowed endpoints are exactly the api_endpoints rows, and nothing
else maps to one."""

import sqlite3

import pytest

from spotivault.store import load_migrations
from spotivault.store.migrate import migrate
from spotivault.webapi import endpoints
from spotivault.webapi.endpoints import (
    ENDPOINTS,
    ME,
    PLAY,
    PLAYLIST,
    PLAYLIST_ITEMS,
    TOKEN,
    endpoint_for,
)

PLAYLIST_ID = "a9poFNKiHX6sRmXWJ3e0mn"


def test_the_list_is_the_api_endpoints_table_in_its_order() -> None:
    conn = sqlite3.connect(":memory:", autocommit=True)
    try:
        migrate(conn, load_migrations())
        rows = conn.execute("SELECT id, method, template, lane FROM api_endpoints ORDER BY id")
        table = [(row[1], row[2], row[3]) for row in rows]
    finally:
        conn.close()
    assert table == [(e.method, e.template, e.lane) for e in ENDPOINTS]


def test_urls() -> None:
    assert ME.url() == "https://api.spotify.com/v1/me"
    assert PLAYLIST_ITEMS.url(id=PLAYLIST_ID) == (
        f"https://api.spotify.com/v1/playlists/{PLAYLIST_ID}/items"
    )
    assert TOKEN.url() == "https://accounts.spotify.com/api/token"
    assert PLAYLIST_ITEMS.name == "GET /playlists/{id}/items"


@pytest.mark.parametrize("bad", ["../me", "abc/items", "abc?x=1", "", "abc def"])
def test_an_id_can_only_be_base62(bad: str) -> None:
    with pytest.raises(ValueError):
        PLAYLIST.url(id=bad)


def test_an_id_is_needed_exactly_where_the_template_has_one() -> None:
    with pytest.raises(ValueError):
        PLAYLIST.url()
    with pytest.raises(ValueError):
        ME.url(id=PLAYLIST_ID)


def test_endpoint_for_maps_the_allowed_requests() -> None:
    base = "https://api.spotify.com/v1"
    assert endpoint_for("GET", f"{base}/playlists/{PLAYLIST_ID}?fields=id") is PLAYLIST
    assert endpoint_for("GET", f"{base}/playlists/{PLAYLIST_ID}/items?limit=50") is PLAYLIST_ITEMS
    assert endpoint_for("PUT", f"{base}/me/player/play?device_id=x") is PLAY
    assert endpoint_for("POST", "https://accounts.spotify.com/api/token") is TOKEN
    for endpoint in ENDPOINTS:
        url = endpoint.url(id=PLAYLIST_ID) if "{id}" in endpoint.template else endpoint.url()
        assert endpoint_for(endpoint.method, url) is endpoint


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "https://api.spotify.com/v1/playlists/x/tracks"),  # removed in 2026
        ("GET", "https://api.spotify.com/v1/tracks?ids=a,b"),  # batch lookups are gone
        ("GET", "https://api.spotify.com/v1/albums?ids=a"),
        ("DELETE", "https://api.spotify.com/v1/me/tracks"),
        ("POST", "https://api.spotify.com/v1/me/player/play"),
        ("GET", "https://spclient.wg.spotify.com/playlist/v2/playlist/x"),  # internal
        ("GET", "https://api-partner.spotify.com/pathfinder/v1/query"),  # internal
        ("GET", "http://api.spotify.com/v1/me"),  # not https
        ("GET", "https://api.spotify.com/me"),  # no /v1
        ("GET", "https://accounts.spotify.com/api/token"),
        ("POST", "https://accounts.spotify.com/authorize"),
    ],
)
def test_anything_else_maps_to_nothing(method: str, url: str) -> None:
    assert endpoint_for(method, url) is None


def test_the_scopes_are_step_5s() -> None:
    assert endpoints.SCOPES == (
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-library-read",
        "user-read-playback-state",
        "user-modify-playback-state",
    )
    assert endpoints.REDIRECT_URI == "http://127.0.0.1:8888/callback"
