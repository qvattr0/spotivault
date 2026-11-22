"""A tiny VNC server for fake mode, so `WS /vnc` shows a screen without Xvfb or x11vnc.

FakeDesktop.open_vnc() runs `serve()` on one end of a socket pair and hands the other end to the
`/vnc` bridge, exactly as a TCP connection to x11vnc would be. It speaks RFB 3.8 (3.3 too) with
no authentication and raw encoding, which noVNC understands.

The screen is drawn from the simulated client (`FakeScreen`):
- **not running:** black, as Xvfb with no window;
- **logged out:** a login screen with a QR code that changes each time the client starts.
  **A click on it logs the client in,** standing in for scanning the code with a phone;
- **logged in:** a dark player window whose bottom bar shows the playing track's progress.

Keys and other clicks are ignored. Owner: the fake agent.
"""

import asyncio
import logging
import random
import struct
from dataclasses import dataclass

from spotivault.fake.client import FakeClientControl
from spotivault.fake.player import SimPlayer

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1280, 800  # Xvfb's screen (design.md § Container)
BAR_Y, BAR_H = HEIGHT - 72, 72  # the player's bottom bar
NAME = b"spotivault fake screen"

type Rgb = tuple[int, int, int]

BLACK: Rgb = (0, 0, 0)
DARK: Rgb = (18, 18, 18)
SIDEBAR: Rgb = (0, 0, 0)
BAR: Rgb = (24, 24, 24)
GREY: Rgb = (83, 83, 83)
GREEN: Rgb = (30, 215, 96)
WHITE: Rgb = (255, 255, 255)


@dataclass(slots=True)
class PixelFormat:
    """RFB's PIXEL_FORMAT. Only 32 bits per pixel, true colour, is served."""

    bits: int = 32
    depth: int = 24
    big_endian: bool = False
    red_max: int = 255
    green_max: int = 255
    blue_max: int = 255
    red_shift: int = 16
    green_shift: int = 8
    blue_shift: int = 0

    def pack(self) -> bytes:
        return struct.pack(
            ">BBBBHHHBBB3x",
            self.bits,
            self.depth,
            int(self.big_endian),
            1,
            self.red_max,
            self.green_max,
            self.blue_max,
            self.red_shift,
            self.green_shift,
            self.blue_shift,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "PixelFormat":
        bits, depth, big, _, rmax, gmax, bmax, rs, gs, bs = struct.unpack(">BBBBHHHBBB3x", data)
        return cls(bits, depth, bool(big), rmax, gmax, bmax, rs, gs, bs)

    def pixel(self, rgb: Rgb) -> bytes:
        red, green, blue = rgb
        value = (
            (red * self.red_max // 255) << self.red_shift
            | (green * self.green_max // 255) << self.green_shift
            | (blue * self.blue_max // 255) << self.blue_shift
        )
        return value.to_bytes(4, "big" if self.big_endian else "little")


class FakeScreen:
    """What the client's window looks like right now."""

    def __init__(self, player: SimPlayer, client: FakeClientControl) -> None:
        self.player = player
        self.client = client
        self.starts = 0  # client starts seen, for a new QR code each time
        self._was_on_bus = False

    def scene(self) -> tuple[str, int]:
        """("off" | "login" | "player", a number that changes when the picture does)."""
        if not self.player.on_bus:
            self._was_on_bus = False
            return "off", 0
        if not self._was_on_bus:
            self._was_on_bus = True
            self.starts += 1
        if not self.player.logged_in:
            return "login", self.starts
        return "player", self.player.position_ms() // 2000 if self.player.entry else -1

    def render(self, fmt: PixelFormat) -> bytes:
        kind, detail = self.scene()
        frame = bytearray(fmt.pixel(BLACK if kind == "off" else DARK) * (WIDTH * HEIGHT))
        if kind == "login":
            self._draw_login(frame, fmt, detail)
        elif kind == "player":
            self._fill(frame, fmt, 0, 0, 240, BAR_Y, SIDEBAR)
            self._draw_bar(frame, fmt)
        return bytes(frame)

    def click(self, x: int, y: int) -> None:
        """A click: on the login screen, it stands in for scanning the QR code."""
        if self.player.on_bus and not self.player.logged_in:
            log.info("fake VNC: a click on the login screen logs the client in")
            self.client.log_in()

    def _draw_login(self, frame: bytearray, fmt: PixelFormat, seed: int) -> None:
        modules, size = 25, 12
        left, top = (WIDTH - modules * size) // 2, 180
        self._fill(frame, fmt, left - 24, top - 24, modules * size + 48, modules * size + 48, WHITE)
        rng = random.Random(seed)
        dark = fmt.pixel(BLACK)
        for row in range(modules):
            line = bytearray(fmt.pixel(WHITE) * (modules * size))
            for col in range(modules):
                finder = _in_finder(row, col, modules)
                if finder or (finder is None and rng.random() < 0.5):
                    start = col * size * 4
                    line[start : start + size * 4] = dark * size
            for dy in range(size):
                offset = ((top + row * size + dy) * WIDTH + left) * 4
                frame[offset : offset + len(line)] = line
        self._fill(frame, fmt, (WIDTH - 280) // 2, top + modules * size + 70, 280, 48, GREEN)

    def _draw_bar(self, frame: bytearray, fmt: PixelFormat) -> None:
        self._fill(frame, fmt, 0, BAR_Y, WIDTH, BAR_H, BAR)
        entry = self.player.entry
        if entry is None or entry.track is None or not entry.track.duration_ms:
            return
        self._fill(frame, fmt, 16, BAR_Y + 12, 48, 48, GREY)  # the cover
        track_left, track_width = 340, 600
        self._fill(frame, fmt, track_left, BAR_Y + 50, track_width, 4, GREY)
        share = min(1.0, self.player.position_ms() / entry.track.duration_ms)
        played = int(track_width * share)
        if played:
            self._fill(frame, fmt, track_left, BAR_Y + 50, played, 4, WHITE)
        button = WHITE if self.player.status == "Playing" else GREY
        self._fill(frame, fmt, WIDTH // 2 - 16, BAR_Y + 8, 32, 32, button)

    @staticmethod
    def _fill(frame: bytearray, fmt: PixelFormat, x: int, y: int, w: int, h: int, rgb: Rgb) -> None:
        row = fmt.pixel(rgb) * w
        for line in range(y, y + h):
            offset = (line * WIDTH + x) * 4
            frame[offset : offset + len(row)] = row


def _in_finder(row: int, col: int, modules: int) -> bool | None:
    """QR finder patterns in three corners: True dark, False light, None outside them."""
    for top, left in ((0, 0), (0, modules - 7), (modules - 7, 0)):
        r, c = row - top, col - left
        if 0 <= r < 7 and 0 <= c < 7:
            ring = r in (0, 6) or c in (0, 6)
            core = 2 <= r <= 4 and 2 <= c <= 4
            return ring or core
    return None


async def serve(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, screen: FakeScreen
) -> None:
    """One RFB connection, until the client goes away."""
    try:
        fmt = await _handshake(reader, writer)
        await _session(reader, writer, screen, fmt)
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()


async def _handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> PixelFormat:
    writer.write(b"RFB 003.008\n")
    await writer.drain()
    version = await reader.readexactly(12)
    if version.startswith(b"RFB 003.003"):
        writer.write(struct.pack(">I", 1))  # 3.3: the server names the security type, None
    else:
        writer.write(bytes([1, 1]))  # one security type: None
        await writer.drain()
        await reader.readexactly(1)
        writer.write(struct.pack(">I", 0))  # SecurityResult: OK
    await writer.drain()
    await reader.readexactly(1)  # ClientInit
    fmt = PixelFormat()
    writer.write(struct.pack(">HH", WIDTH, HEIGHT) + fmt.pack() + struct.pack(">I", len(NAME)))
    writer.write(NAME)
    await writer.drain()
    return fmt


async def _session(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    screen: FakeScreen,
    fmt: PixelFormat,
) -> None:
    """Reads the client's messages and answers update requests. An incremental request is
    answered once the picture changes, checked twice a second."""
    wanted = asyncio.Event()
    full = False  # the next update must be the whole screen
    sent: tuple[str, int] | None = None

    async def read() -> None:
        nonlocal fmt, full
        while True:
            kind = (await reader.readexactly(1))[0]
            if kind == 0:  # SetPixelFormat
                requested = PixelFormat.unpack((await reader.readexactly(19))[3:])
                if requested.bits != 32:
                    raise ConnectionError("fake VNC: only 32 bits per pixel")
                fmt = requested
            elif kind == 2:  # SetEncodings: raw is all there is
                count = struct.unpack(">xH", await reader.readexactly(3))[0]
                await reader.readexactly(4 * count)
            elif kind == 3:  # FramebufferUpdateRequest
                incremental = (await reader.readexactly(9))[0]
                full = full or not incremental
                wanted.set()
            elif kind == 4:  # KeyEvent
                await reader.readexactly(7)
            elif kind == 5:  # PointerEvent
                buttons, x, y = struct.unpack(">BHH", await reader.readexactly(5))
                if buttons & 1:
                    screen.click(x, y)
            elif kind == 6:  # ClientCutText
                length = struct.unpack(">3xI", await reader.readexactly(7))[0]
                await reader.readexactly(length)
            else:
                raise ConnectionError(f"fake VNC: unknown message type {kind}")

    async def send() -> None:
        nonlocal full, sent
        while True:
            await wanted.wait()
            scene = screen.scene()
            if not full and scene == sent:
                await asyncio.sleep(0.5)
                continue
            wanted.clear()
            full = False
            sent = scene
            header = struct.pack(">BxH", 0, 1) + struct.pack(">HHHHi", 0, 0, WIDTH, HEIGHT, 0)
            writer.write(header + screen.render(fmt))
            await writer.drain()

    sender = asyncio.ensure_future(send())
    try:
        await read()
    finally:
        sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:
            pass
