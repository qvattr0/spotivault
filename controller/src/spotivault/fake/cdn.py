"""The simulated image CDN (`ports.ImageCdn`): covers made up from their URL, no network.

Each allowed URL gives a square PNG of one colour, picked from the URL, so covers look different
from each other in fake mode. Its edge comes from the size the URL names, as Spotify's CDN does
(design.md § Spotify's image CDN): an album-art or uploaded-cover size code (`b273` 640,
`1e02` 300, `4851` 64, `bebb` 640, `da84` and `d72c` 300), or a mosaic's `/<size>/`. Any other
allowed URL gives 640 px.

Like the real one, it refuses a URL that isn't https on a Spotify image host (ImageRefused).
Tests steer it: `missing` (URLs that answer 404), `failures` (errors the next fetches raise, in
order), and read `fetched` (every URL asked for, refused ones included).

"""

import hashlib
import re
import struct
import zlib

from spotivault.ports import (
    FetchedImage,
    ImageError,
    ImageNotFound,
    ImageRefused,
    spotify_image_url_allowed,
)

SIZE_CODES = {"b273": 640, "1e02": 300, "4851": 64, "bebb": 640, "da84": 300, "d72c": 300}
_CODED = re.compile(r"/image/ab67[0-9a-f]{4}0000([0-9a-f]{4})[0-9a-f]{24}$")
_MOSAIC = re.compile(r"^https://mosaic\.scdn\.co/(\d+)/")
DEFAULT_EDGE = 640


class FakeImageCdn:
    """`ports.ImageCdn` for fake mode and tests. See the module docstring."""

    def __init__(self) -> None:
        self.fetched: list[str] = []
        self.missing: set[str] = set()  # URLs that answer 404
        self.failures: list[ImageError] = []  # raised by the next fetches, first one first
        self._cache: dict[tuple[int, bytes], bytes] = {}
        self.world: object | None = None  # the FakeWorld it belongs to

    async def fetch(self, url: str) -> FetchedImage:
        self.fetched.append(url)
        if not spotify_image_url_allowed(url):
            raise ImageRefused("not a Spotify image URL")
        if self.failures:
            raise self.failures.pop(0)
        if url in self.missing:
            raise ImageNotFound("no image at this URL")
        edge = edge_for(url)
        colour = hashlib.sha1(url.encode()).digest()[:3]
        key = (edge, colour)
        if key not in self._cache:
            self._cache[key] = solid_png(edge, colour)
        return FetchedImage(
            content_type="image/png", data=self._cache[key], width=edge, height=edge
        )

    async def aclose(self) -> None:
        return None


def edge_for(url: str) -> int:
    """The edge in pixels the URL asks for, as Spotify's CDN names sizes."""
    coded = _CODED.search(url)
    if coded is not None:
        return SIZE_CODES.get(coded.group(1), DEFAULT_EDGE)
    mosaic = _MOSAIC.match(url)
    if mosaic is not None:
        return int(mosaic.group(1))
    return DEFAULT_EDGE


def solid_png(edge: int, rgb: bytes) -> bytes:
    """A square PNG of one colour. A few hundred bytes: every row compresses to almost nothing."""
    row = b"\x00" + rgb * edge  # filter type 0, then the pixels
    raw = row * edge
    header = struct.pack(">IIBBBBB", edge, edge, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)
