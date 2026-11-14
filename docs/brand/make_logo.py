"""Generate the spotibackup logo SVGs ("vinyl vault").

Run from anywhere:  python3 docs/brand/make_logo.py
Writes the SVG files next to this script. The geometry helpers are also used
to build the logo components in docs/ui-design/spotibackup.pen.

All shapes are fills (no strokes), drawn in a 140 x 140 box centred on 0,0,
so they scale cleanly and map 1:1 onto Pencil path nodes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

GREEN = "#34D399"  # label; brand colour, not the UI accent token
INK = "#121212"  # keyhole
DARK_TILE = "#121212"
DARK_RECORD = "#2A2A2A"
DARK_GROOVE = "#3A3A3A"
LIGHT_TILE = "#F2F2F2"
LIGHT_RECORD = "#121212"
LIGHT_GROOVE = "#2E2E2E"

TILE = 140  # tile edge in design units
TILE_RADIUS = 28


def f(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def circle(r: float, cx: float = 0, cy: float = 0) -> str:
    return (
        f"M{f(cx - r)} {f(cy)}A{f(r)} {f(r)} 0 1 0 {f(cx + r)} {f(cy)}"
        f"A{f(r)} {f(r)} 0 1 0 {f(cx - r)} {f(cy)}Z"
    )


def ring(r_mid: float, width: float) -> str:
    """A groove: a ring of the given width, drawn with fill-rule evenodd."""
    return circle(r_mid + width / 2) + circle(r_mid - width / 2)


def notched_disc(r: float, notches: int, half_width: float, cap_centre: float) -> str:
    """The record outline with `notches` round-ended slots cut in from the rim.

    Each slot is 2*half_width wide and runs from the rim inwards to a round end
    whose centre sits at radius cap_centre. Slot 0 is at 12 o'clock.
    """
    if notches == 0:
        return circle(r)
    rim = math.sqrt(r * r - half_width * half_width)
    parts: list[str] = []
    for i in range(notches):
        a = 2 * math.pi * i / notches
        u = (math.sin(a), -math.cos(a))  # outward
        v = (math.cos(a), math.sin(a))  # clockwise tangent
        pa = (u[0] * rim - v[0] * half_width, u[1] * rim - v[1] * half_width)
        pb = (u[0] * cap_centre - v[0] * half_width, u[1] * cap_centre - v[1] * half_width)
        pc = (u[0] * cap_centre + v[0] * half_width, u[1] * cap_centre + v[1] * half_width)
        pd = (u[0] * rim + v[0] * half_width, u[1] * rim + v[1] * half_width)
        if i == 0:
            parts.append(f"M{f(pa[0])} {f(pa[1])}")
        else:
            parts.append(f"A{f(r)} {f(r)} 0 0 1 {f(pa[0])} {f(pa[1])}")
        parts.append(f"L{f(pb[0])} {f(pb[1])}")
        parts.append(f"A{f(half_width)} {f(half_width)} 0 0 0 {f(pc[0])} {f(pc[1])}")
        parts.append(f"L{f(pd[0])} {f(pd[1])}")
        if i == 0:
            start = pa
    parts.append(f"A{f(r)} {f(r)} 0 0 1 {f(start[0])} {f(start[1])}Z")
    return "".join(parts)


def keyhole(cy: float, r: float, top_y: float, top_hw: float, bot_y: float, bot_hw: float) -> str:
    """A round head (centre 0,cy, radius r) merged with a tapered slot."""
    # Where the right side of the slot leaves the head circle.
    lo, hi = 0.0, 1.0
    def inside(t: float) -> bool:
        x = top_hw + (bot_hw - top_hw) * t
        y = top_y + (bot_y - top_y) * t
        return x * x + (y - cy) ** 2 < r * r
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if inside(mid) else (lo, mid)
    x = top_hw + (bot_hw - top_hw) * lo
    y = top_y + (bot_y - top_y) * lo
    return (
        f"M{f(x)} {f(y)}A{f(r)} {f(r)} 0 1 0 {f(-x)} {f(y)}"
        f"L{f(-bot_hw)} {f(bot_y)}L{f(bot_hw)} {f(bot_y)}Z"
    )


@dataclass
class Layer:
    name: str
    d: str
    fill: str
    evenodd: bool = False


@dataclass
class Variant:
    file: str
    size: int  # nominal pixel size
    layers: list[Layer] = field(default_factory=list)
    tile: str | None = None  # tile colour, or None for no tile
    view: tuple[float, float, float, float] = (-70, -70, 140, 140)


# Detail levels. 140 is the master; smaller sizes drop detail.
def record_layers(level: str, record: str, groove: str) -> list[Layer]:
    if level == "full":  # 12 rim notches, two grooves
        return [
            Layer("Record", notched_disc(52, 12, 0.75, 47.75), record),
            Layer("Grooves", ring(40, 1.5) + ring(32, 1.5), groove, evenodd=True),
            Layer("Label", circle(20), GREEN),
            Layer("Keyhole", keyhole(-4, 5.5, -1, 3, 11, 5), INK),
        ]
    if level == "64":  # 8 rim notches, one groove, both thicker
        return [
            Layer("Record", notched_disc(52, 8, 1.5, 46.5), record),
            Layer("Grooves", ring(36, 2.5), groove, evenodd=True),
            Layer("Label", circle(20), GREEN),
            Layer("Keyhole", keyhole(-4, 5.5, -1, 3, 11, 5), INK),
        ]
    if level == "32":  # no notches or grooves
        return [
            Layer("Record", circle(52), record),
            Layer("Label", circle(20), GREEN),
            Layer("Keyhole", keyhole(-4, 5.5, -1, 3, 11, 5), INK),
        ]
    if level == "16":  # bigger record, label and keyhole so they survive
        return [
            Layer("Record", circle(56), record),
            Layer("Label", circle(26), GREEN),
            Layer("Keyhole", keyhole(-5, 8, -1, 4, 14, 7), INK),
        ]
    raise ValueError(level)


VARIANTS = [
    Variant("logo.svg", 512, record_layers("full", DARK_RECORD, DARK_GROOVE), DARK_TILE),
    Variant("logo-light.svg", 512, record_layers("full", LIGHT_RECORD, LIGHT_GROOVE), LIGHT_TILE),
    Variant("logo-64.svg", 64, record_layers("64", DARK_RECORD, DARK_GROOVE), DARK_TILE),
    Variant("logo-32.svg", 32, record_layers("32", DARK_RECORD, DARK_GROOVE), DARK_TILE),
    Variant("logo-16.svg", 16, record_layers("16", DARK_RECORD, DARK_GROOVE), DARK_TILE),
    # The record alone, for placing on a surface; the notches are see-through.
    Variant("mark.svg", 512, record_layers("full", DARK_RECORD, DARK_GROOVE), None, (-52, -52, 104, 104)),
]


def svg(v: Variant) -> str:
    vb = " ".join(f(n) for n in v.view)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{v.size}" height="{v.size}" '
        f'role="img" aria-label="spotibackup">',
        "<title>spotibackup</title>",
    ]
    if v.tile:
        h = TILE / 2
        out.append(
            f'<rect x="{f(-h)}" y="{f(-h)}" width="{TILE}" height="{TILE}" rx="{TILE_RADIUS}" fill="{v.tile}"/>'
        )
    for layer in v.layers:
        rule = ' fill-rule="evenodd"' if layer.evenodd else ""
        out.append(f'<path d="{layer.d}" fill="{layer.fill}"{rule}/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    here = Path(__file__).resolve().parent
    for v in VARIANTS:
        (here / v.file).write_text(svg(v))
        print("wrote", v.file)


if __name__ == "__main__":
    main()
