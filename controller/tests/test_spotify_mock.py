"""The mock Spotify (tests/spotify_mock.py) answers like the 2026 Web API, driven here with a
plain httpx client, so the harness is checked on its own, before the real port uses it."""

import base64
import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest

from spotify_mock import SpotifyMock, UnexpectedRequest, apply_fields, our_device_id
from spotivault.fake.clock import FakeClock
from spotivault.logs import REDACTED, redact
from spotivault.webapi.endpoints import API_BASE, REDIRECT_URI, TOKEN_URL

CAPTURED = "7aUxnM625jyHAtd7b7xZLg"  # Playlist 7: 300 entries, 20 unplayable (S0 row 19)
FOLLOWED = "a9poFNKiHX6sRmXWJ3e0mn"  # the one followed playlist in /me/playlists


@pytest.fixture
def mock(fake_clock: FakeClock) -> SpotifyMock:
    return SpotifyMock(clock=fake_clock, device_name="spotivault-test")


@pytest.fixture
async def http(mock: SpotifyMock) -> AsyncIterator[httpx.AsyncClient]:
    access, _ = mock.issue_tokens()
    headers = {"Authorization": f"Bearer {access}"}
    async with httpx.AsyncClient(transport=mock.transport(), headers=headers) as client:
        yield client


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


async def test_me_and_the_request_log(mock: SpotifyMock, http: httpx.AsyncClient) -> None:
    body = (await http.get(f"{API_BASE}/me")).json()
    assert (body["id"], body["display_name"]) == ("user2", "User One")
    assert mock.endpoints() == ["GET /me"]
    assert mock.requests[0].status == 200 and mock.requests[0].at == 1000.0
    assert mock.count("GET /me") == 1 and mock.count() == 1


async def test_my_playlists_pages_with_2026_names(
    mock: SpotifyMock, http: httpx.AsyncClient
) -> None:
    first = (await http.get(f"{API_BASE}/me/playlists", params={"limit": 10})).json()
    assert (first["total"], first["limit"], len(first["items"])) == (18, 10, 10)
    assert "offset=10" in first["next"]
    second = (await http.get(first["next"])).json()
    assert len(second["items"]) == 8 and second["next"] is None
    playlists = first["items"] + second["items"]
    assert all("tracks" not in p for p in playlists)
    followed = next(p for p in playlists if p["id"] == FOLLOWED)
    assert followed["owner"]["id"] != "user2" and followed["items"]["total"] == 35  # row 20
    assert all(p["snapshot_id"] for p in playlists)


async def test_default_and_bad_limits(http: httpx.AsyncClient) -> None:
    assert (await http.get(f"{API_BASE}/me/tracks")).json()["limit"] == 20
    assert (await http.get(f"{API_BASE}/me/tracks", params={"limit": 51})).status_code == 400
    assert (await http.get(f"{API_BASE}/me/tracks", params={"limit": 0})).status_code == 400
    assert (await http.get(f"{API_BASE}/me/tracks", params={"offset": -1})).status_code == 400


async def test_playlist_items_under_item_with_market(
    mock: SpotifyMock, http: httpx.AsyncClient
) -> None:
    url = f"{API_BASE}/playlists/{CAPTURED}/items"
    page = (await http.get(url, params={"limit": 50, "offset": 0})).json()
    assert page["total"] == 300
    entry = page["items"][0]
    assert "track" not in entry and entry["item"]["id"]
    assert "is_playable" not in entry["item"]  # no market, no is_playable
    page = (await http.get(url, params={"limit": 50, "market": "from_token"})).json()
    playable = [e["item"]["is_playable"] for e in page["items"]]
    assert playable[2] is False and playable[20] is False and playable.count(False) == 2
    assert "market=from_token" in page["next"]


async def test_odd_entries(mock: SpotifyMock, http: httpx.AsyncClient) -> None:
    playlist = next(p for p in mock.catalog.playlists.values() if p.playlist.name == "Playlist 3")
    url = f"{API_BASE}/playlists/{playlist.playlist.id}/items"
    items = (await http.get(url, params={"limit": 50})).json()["items"]
    assert items[4]["is_local"] is True and items[4]["item"]["id"] is None
    assert items[8]["item"]["episode"] is True and items[8]["item"]["track"] is False
    assert items[11]["item"] is None


async def test_access_rules(mock: SpotifyMock, http: httpx.AsyncClient) -> None:
    linked = next(p for p in mock.catalog.playlists.values() if p.access == "linked")
    spotify = next(p for p in mock.catalog.playlists.values() if p.access == "spotify")
    assert (await http.get(f"{API_BASE}/playlists/{FOLLOWED}/items")).status_code == 403
    assert (await http.get(f"{API_BASE}/playlists/{linked.playlist.id}/items")).status_code == 403
    body = (await http.get(f"{API_BASE}/playlists/{linked.playlist.id}")).json()
    assert body["name"] == "Linked Mix" and "items" not in body and body["snapshot_id"]  # row 29
    assert (await http.get(f"{API_BASE}/playlists/{spotify.playlist.id}")).status_code == 404
    error = (await http.get(f"{API_BASE}/playlists/{spotify.playlist.id}/items")).json()
    assert error == {"error": {"status": 404, "message": "Resource not found"}}  # row 28
    assert (await http.get(f"{API_BASE}/playlists/{'Z' * 22}")).status_code == 404
    owned = (await http.get(f"{API_BASE}/playlists/{CAPTURED}")).json()
    assert owned["items"]["total"] == 300 and len(owned["items"]["items"]) == 100


async def test_fields_are_applied(http: httpx.AsyncClient) -> None:
    fields = "id,name,owner(id),items(total)"
    body = (await http.get(f"{API_BASE}/playlists/{CAPTURED}", params={"fields": fields})).json()
    assert body == {
        "id": CAPTURED,
        "name": body["name"],
        "owner": {"id": "user2"},
        "items": {"total": 300},
    }
    fields = "total,items(added_at,item(id,artists(name)))"
    page = (
        await http.get(
            f"{API_BASE}/playlists/{CAPTURED}/items", params={"fields": fields, "limit": 2}
        )
    ).json()
    assert set(page) == {"total", "items"}
    assert set(page["items"][0]) == {"added_at", "item"}
    assert set(page["items"][0]["item"]) == {"id", "artists"}


def test_apply_fields_grammar() -> None:
    value = {"a": 1, "b": {"c": 2, "d": 3}, "e": [{"f": 4, "g": 5}], "h": {"i": {"j": 6, "k": 7}}}
    assert apply_fields(value, "a") == {"a": 1}
    assert apply_fields(value, "b(c),e(g)") == {"b": {"c": 2}, "e": [{"g": 5}]}
    assert apply_fields(value, "h.i.j") == {"h": {"i": {"j": 6}}}
    assert apply_fields(value, "b(c),b") == {"b": {"c": 2, "d": 3}}  # all of it wins
    assert apply_fields(value, "missing,a") == {"a": 1}
    with pytest.raises(ValueError):
        apply_fields(value, "b(c")


async def test_liked_songs_and_albums_keep_their_names(
    mock: SpotifyMock, http: httpx.AsyncClient
) -> None:
    liked = (await http.get(f"{API_BASE}/me/tracks", params={"limit": 50})).json()
    assert liked["total"] == 277 and liked["items"][0]["track"]["id"]
    assert liked["items"][0]["added_at"] >= liked["items"][1]["added_at"]  # newest first
    albums = (
        await http.get(f"{API_BASE}/me/albums", params={"limit": 50, "market": "from_token"})
    ).json()
    assert albums["total"] == 124
    album = albums["items"][0]["album"]
    assert album["tracks"]["items"] and "album" not in album["tracks"]["items"][0]
    assert album["tracks"]["total"] == album["total_tracks"]
    tracks = (await http.get(f"{API_BASE}/albums/{album['id']}/tracks")).json()
    assert tracks["total"] == album["total_tracks"]
    assert (await http.get(f"{API_BASE}/albums/{'Z' * 22}/tracks")).status_code == 404


async def test_devices_and_the_player(mock: SpotifyMock, http: httpx.AsyncClient) -> None:
    devices = (await http.get(f"{API_BASE}/me/player/devices")).json()["devices"]
    assert devices[0]["name"] == "spotivault-test" and len(devices) == 4
    assert devices[0]["id"] == our_device_id(mock)
    mock.our_device_listed = False
    devices = (await http.get(f"{API_BASE}/me/player/devices")).json()["devices"]
    assert "spotivault-test" not in [d["name"] for d in devices]
    mock.our_device_listed = True
    assert (await http.get(f"{API_BASE}/me/player")).status_code == 204
    body = {"context_uri": f"spotify:playlist:{CAPTURED}", "offset": {"uri": "spotify:track:x"}}
    play = await http.put(
        f"{API_BASE}/me/player/play", params={"device_id": our_device_id(mock)}, json=body
    )
    assert play.status_code == 204 and mock.requests[-1].json == body
    assert mock.active_device_id == our_device_id(mock)
    bad = await http.put(f"{API_BASE}/me/player/pause", params={"device_id": "nope"})
    assert bad.status_code == 404
    mock.player_state = {"is_playing": True}
    assert (await http.get(f"{API_BASE}/me/player")).json() == {"is_playing": True}


async def test_tokens_are_checked(mock: SpotifyMock, http: httpx.AsyncClient) -> None:
    async with httpx.AsyncClient(transport=mock.transport()) as anonymous:
        assert (await anonymous.get(f"{API_BASE}/me")).status_code == 401
    mock.expire_access_tokens()
    response = await http.get(f"{API_BASE}/me")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "The access token expired"


async def test_pkce_exchange_then_refresh_with_rotation(mock: SpotifyMock) -> None:
    verifier = "v" * 64
    code = mock.authorize(code_challenge=challenge(verifier))
    async with httpx.AsyncClient(transport=mock.transport()) as http:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": mock.client_id,
            "code_verifier": verifier,
        }
        grant = (await http.post(TOKEN_URL, data=form)).json()
        assert grant["token_type"] == "Bearer" and grant["expires_in"] == 3600
        assert grant["scope"].split() == list(
            ("playlist-read-private playlist-read-collaborative user-library-read "
             "user-read-playback-state user-modify-playback-state").split()
        )  # fmt: skip
        again = await http.post(TOKEN_URL, data=form)  # codes are single use
        assert again.status_code == 400 and again.json()["error"] == "invalid_grant"

        me = await http.get(
            f"{API_BASE}/me", headers={"Authorization": f"Bearer {grant['access_token']}"}
        )
        assert me.status_code == 200

        refresh = {"grant_type": "refresh_token", "refresh_token": grant["refresh_token"]}
        refresh["client_id"] = mock.client_id
        renewed = (await http.post(TOKEN_URL, data=refresh)).json()
        assert renewed["access_token"] != grant["access_token"]
        assert renewed["refresh_token"] != grant["refresh_token"]
        stale = await http.post(TOKEN_URL, data=refresh)  # the old refresh token was retired
        assert stale.json()["error"] == "invalid_grant"

        mock.revoke_refresh_tokens()
        refresh["refresh_token"] = renewed["refresh_token"]
        revoked = await http.post(TOKEN_URL, data=refresh)
        assert revoked.status_code == 400
        assert revoked.json() == {
            "error": "invalid_grant",
            "error_description": "Refresh token revoked",
        }


async def test_a_wrong_verifier_or_a_json_body_is_refused(mock: SpotifyMock) -> None:
    code = mock.authorize(code_challenge=challenge("right"))
    async with httpx.AsyncClient(transport=mock.transport()) as http:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": mock.client_id,
            "code_verifier": "wrong",
        }
        assert (await http.post(TOKEN_URL, data=form)).json()["error"] == "invalid_grant"
        assert (await http.post(TOKEN_URL, json=form)).json()["error"] == "invalid_request"


async def test_scripted_failures_come_first_and_in_order(
    mock: SpotifyMock, http: httpx.AsyncClient
) -> None:
    mock.fail("GET /me/tracks", status=429, retry_after_s=3)
    mock.fail("GET /me/tracks", status=503, times=2)
    mock.fail(None, status=502)
    first = await http.get(f"{API_BASE}/me/tracks")
    assert first.status_code == 429 and first.headers["retry-after"] == "3"
    assert first.json() == {"error": {"status": 429, "message": "API rate limit exceeded"}}
    assert [(await http.get(f"{API_BASE}/me/tracks")).status_code for _ in range(2)] == [503, 503]
    assert (await http.get(f"{API_BASE}/me")).status_code == 502  # any endpoint
    assert (await http.get(f"{API_BASE}/me/tracks")).status_code == 200
    mock.timeout("GET /me/player/devices")
    with pytest.raises(httpx.ReadTimeout):
        await http.get(f"{API_BASE}/me/player/devices")
    assert mock.requests[-1].status is None
    mock.network_error(None)
    with pytest.raises(httpx.ConnectError):
        await http.get(f"{API_BASE}/me")
    mock.fail("POST /api/token", status=400)
    refused = await http.post(TOKEN_URL, data={"grant_type": "refresh_token"})
    assert refused.json()["error"] == "invalid_grant"
    with pytest.raises(ValueError):
        mock.fail("GET /playlists/{id}/tracks", status=500)


async def test_anything_else_is_refused_loudly(mock: SpotifyMock, http: httpx.AsyncClient) -> None:
    for method, url in [
        ("GET", f"{API_BASE}/playlists/{CAPTURED}/tracks"),
        ("GET", f"{API_BASE}/tracks?ids=a"),
        ("GET", "https://spclient.wg.spotify.com/metadata/4/track/x"),
        ("DELETE", f"{API_BASE}/me/tracks"),
    ]:
        with pytest.raises(UnexpectedRequest):
            await http.request(method, url)
    assert len(mock.unexpected) == 4 and mock.unexpected[0].endpoint is None


def test_tokens_look_like_spotifys_so_redaction_catches_them(mock: SpotifyMock) -> None:
    access, refresh = mock.issue_tokens()
    code = mock.authorize(code_challenge="x")
    assert access.startswith("BQ") and refresh.startswith("AQ") and code.startswith("AQ")
    for secret in (access, refresh, code):
        assert redact(f"token {secret} leaked") == f"token {REDACTED} leaked"
