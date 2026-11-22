"""The image CDN port: only Spotify's image hosts over https, a size cap, JPEG or PNG only; and
the fake one, which never touches the network."""

import struct

import httpx
import pytest

from portcheck import assert_implements
from spotivault import ports
from spotivault.fake.cdn import FakeImageCdn, edge_for, solid_png
from spotivault.imagecdn import HttpImageCdn, image_info
from spotivault.ports import (
    ImageFetchFailed,
    ImageNotFound,
    ImageRefused,
    spotify_image_url_allowed,
)

ALBUM_640 = "https://i.scdn.co/image/ab67616d0000b273a5a8fb8d51934d96766181d9"
PLAYLIST = "https://image-cdn-ak.spotifycdn.com/image/ab67706c0000bebbd17e192d4a08b8d87b6baa18"
MOSAIC = "https://mosaic.scdn.co/640/ab67616d0000b273" + "a" * 24


def tiny_jpeg(width: int, height: int) -> bytes:
    """SOI, an APP0 segment, then a baseline SOF0 with the size: enough for image_info."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


@pytest.mark.parametrize(
    "url",
    [
        ALBUM_640,
        PLAYLIST,
        MOSAIC,
        "https://image-cdn-fa.spotifycdn.com/image/ab67706c0000da84" + "b" * 24,
        "https://I.SCDN.CO/image/x",
        "https://i.scdn.co:443/image/x",
    ],
)
def test_spotify_image_hosts_are_allowed(url: str) -> None:
    assert spotify_image_url_allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://i.scdn.co/image/x",  # not https
        "https://i.scdn.co.evil.example/image/x",
        "https://evil.example/i.scdn.co/image/x",
        "https://user:pass@i.scdn.co/image/x",
        "https://i.scdn.co:8443/image/x",
        "https://api.spotify.com/v1/me",
        "https://image-cdn-ak.spotifycdn.com.evil.example/image/x",
        "https://xi.scdn.co/image/x",
        "file:///etc/passwd",
        "https://169.254.169.254/latest/meta-data",
        "not a url",
        "https://i.scdn.co:notaport/x",
    ],
)
def test_everything_else_is_refused(url: str) -> None:
    assert not spotify_image_url_allowed(url)


def test_both_implement_the_port() -> None:
    assert_implements(HttpImageCdn, ports.ImageCdn)
    assert_implements(FakeImageCdn, ports.ImageCdn)


def test_image_info_reads_png_and_jpeg_headers() -> None:
    assert image_info(solid_png(300, b"\x10\x20\x30")) == ("image/png", 300, 300)
    assert image_info(tiny_jpeg(640, 480)) == ("image/jpeg", 640, 480)
    assert image_info(b"\xff\xd8\xff") == ("image/jpeg", None, None)
    assert image_info(b"GIF89a....") is None
    assert image_info(b"<html>") is None


def cdn(handler: httpx.MockTransport, **kwargs: int) -> HttpImageCdn:
    return HttpImageCdn(transport=handler, **kwargs)


async def test_a_jpeg_is_fetched() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=tiny_jpeg(640, 640))

    images = cdn(httpx.MockTransport(handle))
    try:
        image = await images.fetch(ALBUM_640)
    finally:
        await images.aclose()
    assert (image.content_type, image.width, image.height) == ("image/jpeg", 640, 640)
    assert str(seen[0].url) == ALBUM_640
    assert "authorization" not in seen[0].headers  # no token goes to the CDN


async def test_a_refused_url_sends_nothing() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing may be sent")

    images = cdn(httpx.MockTransport(handle))
    with pytest.raises(ImageRefused):
        await images.fetch("https://evil.example/cover.jpg")
    await images.aclose()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(404), ImageNotFound),
        (httpx.Response(500), ImageFetchFailed),
        (httpx.Response(302, headers={"location": "https://evil.example/x"}), ImageFetchFailed),
        (httpx.Response(200, content=b"<html>not an image</html>"), ImageFetchFailed),
        (httpx.Response(200, content=b"GIF89a" + b"\x00" * 20), ImageFetchFailed),
    ],
)
async def test_failures(response: httpx.Response, error: type[Exception]) -> None:
    images = cdn(httpx.MockTransport(lambda request: response))
    with pytest.raises(error):
        await images.fetch(ALBUM_640)
    await images.aclose()


async def test_too_large_is_refused_while_reading() -> None:
    body = solid_png(64, b"\x00\x00\x00") + b"\x00" * 5000
    images = cdn(httpx.MockTransport(lambda request: httpx.Response(200, content=body)))
    images.max_bytes = 1000
    with pytest.raises(ImageFetchFailed, match="too large"):
        await images.fetch(ALBUM_640)
    await images.aclose()


async def test_network_errors_and_timeouts_fail() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    for handler in (timeout, refused):
        images = cdn(httpx.MockTransport(handler))
        with pytest.raises(ImageFetchFailed):
            await images.fetch(ALBUM_640)
        await images.aclose()


async def test_aclose_without_a_fetch() -> None:
    await HttpImageCdn().aclose()


def test_fake_sizes_follow_the_cdn_codes() -> None:
    assert edge_for(ALBUM_640) == 640
    assert edge_for(ALBUM_640.replace("b273", "1e02")) == 300
    assert edge_for(ALBUM_640.replace("b273", "4851")) == 64
    assert edge_for(PLAYLIST.replace("bebb", "da84")) == 300
    assert edge_for("https://mosaic.scdn.co/300/abc") == 300
    assert edge_for("https://image-cdn-ak.spotifycdn.com/image/" + "c" * 40) == 640


async def test_the_fake_makes_distinct_pngs_and_refuses_like_the_real_one() -> None:
    fake = FakeImageCdn()
    first = await fake.fetch(ALBUM_640)
    second = await fake.fetch(ALBUM_640.replace("a5a8", "b5a8"))
    thumb = await fake.fetch(ALBUM_640.replace("b273", "1e02"))
    assert first.content_type == "image/png" and (first.width, first.height) == (640, 640)
    assert image_info(first.data) == ("image/png", 640, 640)
    assert first.data != second.data
    assert (thumb.width, thumb.height) == (300, 300)
    with pytest.raises(ImageRefused):
        await fake.fetch("http://i.scdn.co/image/x")
    fake.missing.add(MOSAIC)
    with pytest.raises(ImageNotFound):
        await fake.fetch(MOSAIC)
    fake.failures.append(ImageFetchFailed("boom"))
    with pytest.raises(ImageFetchFailed):
        await fake.fetch(ALBUM_640)
    assert len(fake.fetched) == 6
