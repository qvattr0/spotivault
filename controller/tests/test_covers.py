"""Cover thumbnails (catalog/covers.py, api/routers/covers.py): the image ID, the size rules,
the cache (downloaded only when the image ID changes), the fallbacks, refusing hosts that aren't
Spotify's, and the two cover endpoints. Downloads go through the fake CDN: nothing is requested
from the network.
"""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import contract
from spotivault.catalog.covers import (
    CoverService,
    full_url,
    image_id_of,
    listed_thumbnail,
    thumbnail_url,
)
from spotivault.fake import world_of
from spotivault.fake.cdn import FakeImageCdn
from spotivault.ports import Image, ImageFetchFailed
from spotivault.services import Services

ID_ONE = "d17e192d4a08b8d87b6baa18"
ID_TWO = "a5a8fb8d51934d96766181d9"


def uploaded(image_id: str, size: str) -> str:
    return f"https://i.scdn.co/image/ab67706c0000{size}{image_id}"


def album_art(image_id: str, size: str) -> str:
    return f"https://i.scdn.co/image/ab67616d0000{size}{image_id}"


def mosaic(ids: str, size: int) -> str:
    return f"https://mosaic.scdn.co/{size}/{ids}"


# --- The rules ----------------------------------------------------------------------------------


def test_the_image_id_is_the_same_for_every_size() -> None:
    assert image_id_of(uploaded(ID_ONE, "bebb")) == ID_ONE
    assert image_id_of(uploaded(ID_ONE, "da84")) == ID_ONE
    assert image_id_of(album_art(ID_TWO, "b273")) == ID_TWO
    assert image_id_of(mosaic("abc123ABC123abc123ABC1", 300)) == "abc123ABC123abc123ABC1"
    # Any other shape: the last path segment, if it's only letters and digits.
    assert image_id_of("https://i.scdn.co/image/" + "c" * 40) == "c" * 40
    assert image_id_of("https://example.com/a/cover.jpg") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://mosaic.scdn.co/640/" + "a" * 40 + "/..",
        "https://mosaic.scdn.co/640/" + "a" * 40 + "/x.jpg",
        "https://i.scdn.co/image/..%2F..%2Fsecret",
        "https://i.scdn.co/",
        "https://i.scdn.co/image/" + "a" * 201,
    ],
)
def test_an_image_id_that_is_not_letters_and_digits_is_refused(url: str) -> None:
    assert image_id_of(url) is None


def test_a_mosaic_id_never_carries_a_query_or_a_folder() -> None:
    # Not the mosaic shape: the last path segment, which has neither.
    assert image_id_of(mosaic("abc", 640) + "?v=1#top") == "abc"
    assert image_id_of(mosaic("abc", 640) + "/x") == "x"


def test_a_listed_300_px_image_is_used_as_listed() -> None:
    images = [
        Image(album_art(ID_ONE, "b273"), 640, 640),
        Image(album_art(ID_ONE, "1e02"), 300, 300),
    ]

    assert thumbnail_url(images) == (album_art(ID_ONE, "1e02"), None)
    assert listed_thumbnail(images) is images[1]


def test_an_uploaded_cover_without_a_listed_300_is_rewritten_with_the_listed_fallback() -> None:
    listed = uploaded(ID_ONE, "d72c")
    images = [Image(listed, None, None)]

    assert thumbnail_url(images) == (uploaded(ID_ONE, "da84"), listed)


def test_album_art_is_rewritten_to_300_for_the_thumbnail_only() -> None:
    listed = album_art(ID_TWO, "b273")
    images = [Image(listed, 640, 640)]

    assert thumbnail_url(images) == (album_art(ID_TWO, "1e02"), listed)
    # The full size of album art is the 640 px the Web API gives: as listed.
    assert full_url(images) == (listed, None)


def test_a_mosaic_is_rewritten_to_300_and_to_1280() -> None:
    listed = mosaic("ids1", 60)
    images = [Image(listed, None, None)]

    assert thumbnail_url(images) == (mosaic("ids1", 300), listed)
    assert full_url(images) == (mosaic("ids1", 1280), listed)


def test_an_uploaded_cover_has_its_largest_size_as_the_full_image() -> None:
    listed = uploaded(ID_ONE, "da84")
    images = [Image(listed, 300, 300)]

    assert full_url(images) == (uploaded(ID_ONE, "bebb"), listed)


def test_a_url_with_no_size_rule_is_downloaded_as_listed() -> None:
    url = "https://i.scdn.co/image/ab67656d0000b273" + ID_ONE
    images = [Image(url, None, None)]

    assert thumbnail_url(images) == (url, None)
    assert full_url(images) == (url, None)


def test_no_images_means_no_cover() -> None:
    assert thumbnail_url([]) is None
    assert full_url([]) is None


# --- The cache ----------------------------------------------------------------------------------


async def insert_album(services: Services, item_id: str) -> None:
    await services.store.execute(
        "INSERT INTO items (id, kind, uri, name, artist, tracked, added_by, added_at, total) "
        "VALUES (?, 'album', ?, 'Cover test', 'Artist', 1, 'user', "
        "'2026-11-15T10:00:00.000Z', 0)",
        (item_id, f"spotify:album:{item_id}"),
    )


def album_images(image_id: str) -> list[Image]:
    return [
        Image(album_art(image_id, "b273"), 640, 640),
        Image(album_art(image_id, "1e02"), 300, 300),
    ]


async def row_of(services: Services, item_id: str) -> Any:
    return await services.store.fetchone(
        "SELECT image_id, thumb_path, full_path, cover_source FROM items WHERE id = ?", (item_id,)
    )


@pytest.fixture
async def ready(running_app: FastAPI, services: Services) -> Services:
    await insert_album(services, "AlbumCover123456789012")
    return services


async def test_a_new_cover_is_saved_both_sizes_and_an_unchanged_one_is_not_downloaded(
    ready: Services,
) -> None:
    item = "AlbumCover123456789012"
    cdn = world_of(ready.ports).cdn

    first = await ready.covers.update(item, album_images(ID_ONE))

    assert (first.outcome, first.image_id) == ("saved", ID_ONE)
    row = await row_of(ready, item)
    assert row["cover_source"] == "spotify" and row["image_id"] == ID_ONE
    cache = ready.config.covers_cache_dir
    assert (cache / row["thumb_path"]).is_file() and (cache / row["full_path"]).is_file()
    assert cdn.fetched == [album_art(ID_ONE, "1e02"), album_art(ID_ONE, "b273")]

    again = await ready.covers.update(item, album_images(ID_ONE))

    assert again.outcome == "unchanged"
    assert len(cdn.fetched) == 2  # nothing new asked for


async def test_a_changed_image_id_downloads_again_and_removes_the_old_files(
    ready: Services,
) -> None:
    item = "AlbumCover123456789012"
    await ready.covers.update(item, album_images(ID_ONE))
    before = await row_of(ready, item)

    changed = await ready.covers.update(item, album_images(ID_TWO))

    assert (changed.outcome, changed.image_id) == ("saved", ID_TWO)
    after = await row_of(ready, item)
    cache = ready.config.covers_cache_dir
    assert not (cache / before["thumb_path"]).exists()
    assert not (cache / before["full_path"]).exists()
    assert (cache / after["thumb_path"]).is_file() and (cache / after["full_path"]).is_file()


async def test_a_thumbnail_the_cdn_lacks_falls_back_to_the_size_returned(ready: Services) -> None:
    item = "AlbumCover123456789012"
    listed = uploaded(ID_ONE, "d72c")  # a playlist's cover, as listed without a width
    cdn = world_of(ready.ports).cdn
    cdn.missing.add(uploaded(ID_ONE, "da84"))  # the 300 px rewrite isn't there

    result = await ready.covers.update(item, [Image(listed, None, None)])

    assert result.outcome == "fallback"
    row = await row_of(ready, item)
    assert row["image_id"] == ID_ONE
    assert uploaded(ID_ONE, "da84") in cdn.fetched and listed in cdn.fetched
    assert (ready.config.covers_cache_dir / row["thumb_path"]).is_file()


async def test_a_full_image_the_cdn_lacks_is_saved_as_returned(ready: Services) -> None:
    item = "AlbumCover123456789012"
    world_of(ready.ports).cdn.missing.add(uploaded(ID_ONE, "bebb"))

    result = await ready.covers.update(item, [Image(uploaded(ID_ONE, "da84"), 300, 300)])

    assert result.outcome == "saved"  # the thumbnail was the listed one: no fallback counted
    row = await row_of(ready, item)
    assert row["full_path"] is not None
    assert (ready.config.covers_cache_dir / row["full_path"]).is_file()


async def test_a_failed_download_keeps_the_cover_that_was_cached(ready: Services) -> None:
    item = "AlbumCover123456789012"
    await ready.covers.update(item, album_images(ID_ONE))
    before = await row_of(ready, item)
    world_of(ready.ports).cdn.failures.append(ImageFetchFailed("the network dropped"))

    result = await ready.covers.update(item, album_images(ID_TWO))

    assert (result.outcome, result.image_id) == ("failed", ID_ONE)
    after = await row_of(ready, item)
    assert after["image_id"] == ID_ONE and after["thumb_path"] == before["thumb_path"]
    assert (ready.config.covers_cache_dir / after["thumb_path"]).is_file()


async def test_a_host_that_is_not_spotifys_is_refused_before_any_request(ready: Services) -> None:
    item = "AlbumCover123456789012"
    cdn = world_of(ready.ports).cdn
    elsewhere = [Image("https://example.com/cover.jpg", 640, 640)]
    plain_http = [Image("http://i.scdn.co/image/ab67616d0000b273" + ID_ONE, 640, 640)]

    for images in (elsewhere, plain_http):
        result = await ready.covers.update(item, images)
        assert result.outcome == "failed"

    assert cdn.fetched == []  # not even asked
    row = await row_of(ready, item)
    assert row["image_id"] is None and row["thumb_path"] is None


async def test_a_url_of_no_known_shape_is_not_downloaded(ready: Services) -> None:
    item = "AlbumCover123456789012"
    cdn = world_of(ready.ports).cdn
    odd = [Image("https://mosaic.scdn.co/640/" + "a" * 40 + "/x.jpg", 640, 640)]

    result = await ready.covers.update(item, odd)

    assert (result.outcome, result.image_id) == ("failed", None)
    assert cdn.fetched == []
    row = await row_of(ready, item)
    assert row["image_id"] is None and row["thumb_path"] is None


async def test_a_stored_file_name_with_a_folder_part_is_never_read(ready: Services) -> None:
    item = "AlbumCover123456789012"
    secret = ready.config.covers_cache_dir.parent / "secret.png"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_bytes(b"\x89PNG not a cover")
    await ready.store.execute(
        "UPDATE items SET thumb_path = '../secret.png', full_path = '../secret.png' WHERE id = ?",
        (item,),
    )

    assert await ready.covers.image(item, "thumb") is None
    assert await ready.covers.image(item, "full") is None
    await ready.covers.update(item, [])  # the old names are never unlinked either
    assert secret.is_file()


async def test_no_images_clears_the_cover(ready: Services) -> None:
    item = "AlbumCover123456789012"
    await ready.covers.update(item, album_images(ID_ONE))
    before = await row_of(ready, item)

    result = await ready.covers.update(item, [])

    assert (result.outcome, result.image_id) == ("none", None)
    row = await row_of(ready, item)
    assert row["cover_source"] == "none" and row["thumb_path"] is None and row["full_path"] is None
    assert not (ready.config.covers_cache_dir / before["thumb_path"]).exists()


async def test_the_image_comes_from_the_cache_and_full_falls_back_to_the_thumbnail(
    ready: Services,
) -> None:
    item = "AlbumCover123456789012"
    await ready.covers.update(item, album_images(ID_ONE))

    thumb = await ready.covers.image(item, "thumb")
    full = await ready.covers.image(item, "full")

    assert thumb is not None and thumb.content_type == "image/png"
    assert thumb.data.startswith(b"\x89PNG")
    assert full is not None and full.data.startswith(b"\x89PNG")
    await ready.store.execute("UPDATE items SET full_path = NULL WHERE id = ?", (item,))
    assert (await ready.covers.image(item, "full")).data == thumb.data  # type: ignore[union-attr]
    assert await ready.covers.image("NoSuchItem123456789012", "thumb") is None


async def test_liked_songs_has_no_cover(ready: Services) -> None:
    await ready.store.execute(
        "INSERT OR IGNORE INTO items (id, kind, uri, name, tracked, added_by, added_at, total) "
        "VALUES ('liked', 'liked', 'spotify:user:x:collection', 'Liked Songs', 1, 'auto', "
        "'2026-11-15T10:00:00.000Z', 0)"
    )

    assert await ready.covers.image("liked", "thumb") is None


async def test_fake_mode_serves_covers_from_the_simulated_cdn(ready: Services) -> None:
    """Fake mode: the CDN is the fake one, so covers cost no network."""
    assert isinstance(ready.ports.cdn, FakeImageCdn)
    assert isinstance(ready.covers, CoverService)


# --- Endpoints ----------------------------------------------------------------------------------


async def test_the_cover_endpoints_serve_the_cached_image(
    client: httpx.AsyncClient, services: Services
) -> None:
    item = "AlbumCover123456789012"
    await insert_album(services, item)
    await services.covers.update(item, album_images(ID_ONE))

    thumb = await client.get(f"/api/albums/{item}/cover")
    full = await client.get(f"/api/albums/{item}/cover", params={"size": "full"})

    for response in (thumb, full):
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "private, max-age=86400"
        contract.assert_response(response, "/api/albums/{id}/cover")
    library = await client.get(f"/api/library/{item}/cover")
    assert library.status_code == 200
    contract.assert_response(library, "/api/library/{id}/cover")


async def test_a_missing_cover_answers_404(client: httpx.AsyncClient, services: Services) -> None:
    response = await client.get("/api/albums/NoSuchItem123456789012/cover")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    contract.assert_response(response, "/api/albums/{id}/cover")
