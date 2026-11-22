"""The real `ports.ImageCdn`: cover downloads from Spotify's image hosts, and nothing else.

Rules (design.md § Spotify's image CDN, the S5 plan):
- **Only Spotify's image hosts, over https** (`ports.spotify_image_url_allowed`). Anything else is
  refused before a request is made. Redirects aren't followed: a 3xx is a failure.
- **A size cap and a timeout:** the body is read in chunks and dropped past MAX_IMAGE_BYTES, and
  the whole download must finish within IMAGE_TIMEOUT_S.
- **Only JPEG and PNG,** told by the first bytes, whatever Content-Type says.
- **Not the Web API:** these requests carry no token, and aren't in the usage log.

Fake mode and the tests use `fake.cdn.FakeImageCdn` instead, so they never reach the network.
"""

import asyncio
import struct

import httpx

from spotivault.ports import (
    IMAGE_TIMEOUT_S,
    MAX_IMAGE_BYTES,
    FetchedImage,
    ImageFetchFailed,
    ImageNotFound,
    ImageRefused,
    spotify_image_url_allowed,
)

USER_AGENT = "spotivault"


class HttpImageCdn:
    """Downloads covers with httpx. The client is made on first use, and closed by `aclose`."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_bytes: int = MAX_IMAGE_BYTES,
        timeout_s: float = IMAGE_TIMEOUT_S,
    ) -> None:
        self._transport = transport  # tests pass an httpx.MockTransport
        self.max_bytes = max_bytes
        self.timeout_s = timeout_s
        self._http: httpx.AsyncClient | None = None

    async def fetch(self, url: str) -> FetchedImage:
        if not spotify_image_url_allowed(url):
            raise ImageRefused("not a Spotify image URL")
        try:
            # One deadline for the whole download, on top of httpx's per-read timeouts.
            async with asyncio.timeout(self.timeout_s):
                data = await self._download(url)
        except TimeoutError as exc:
            raise ImageFetchFailed("the image took too long") from exc
        except httpx.HTTPError as exc:
            raise ImageFetchFailed(f"network error: {type(exc).__name__}") from exc
        info = image_info(data)
        if info is None:
            raise ImageFetchFailed("not a JPEG or PNG")
        content_type, width, height = info
        return FetchedImage(content_type=content_type, data=data, width=width, height=height)

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _download(self, url: str) -> bytes:
        http = self._client()
        async with http.stream("GET", url) as response:
            if response.status_code == 404:
                raise ImageNotFound("no image at this URL")
            if response.status_code != 200:
                raise ImageFetchFailed(f"the CDN answered {response.status_code}")
            declared = response.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
                raise ImageFetchFailed("the image is too large")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self.max_bytes:
                    raise ImageFetchFailed("the image is too large")
                chunks.append(chunk)
        return b"".join(chunks)

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(self.timeout_s),
                follow_redirects=False,
                headers={"User-Agent": USER_AGENT},
            )
        return self._http


# --- Reading an image's type and size from its first bytes ---------------------------------------

_PNG = b"\x89PNG\r\n\x1a\n"
# JPEG start-of-frame markers, which carry the size: SOF0–SOF15 but DHT, JPG and DAC.
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def image_info(data: bytes) -> tuple[str, int | None, int | None] | None:
    """("image/jpeg" or "image/png", width, height), or None when `data` is neither. The size is
    None when the header can't be read. Pure and quick: it only reads headers."""
    if data.startswith(_PNG):
        if len(data) >= 24 and data[12:16] == b"IHDR":
            width, height = struct.unpack(">II", data[16:24])
            return "image/png", width, height
        return "image/png", None, None
    if data.startswith(b"\xff\xd8\xff"):
        width, height = _jpeg_size(data)
        return "image/jpeg", width, height
    return None


def _jpeg_size(data: bytes) -> tuple[int | None, int | None]:
    """Walks the JPEG's marker segments to its start-of-frame, which holds the size."""
    index = 2
    while index + 4 <= len(data):
        if data[index] != 0xFF:
            return None, None
        marker = data[index + 1]
        if marker == 0xFF:  # fill byte
            index += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # no length
            index += 2
            continue
        (length,) = struct.unpack(">H", data[index + 2 : index + 4])
        if marker in _SOF and index + 9 <= len(data):
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return width, height
        if marker == 0xDA:  # start of scan: no frame header before it
            return None, None
        index += 2 + length
    return None, None
