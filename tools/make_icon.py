#!/usr/bin/env python3
"""Render the integration icon (original artwork: charge gauge + bolt + data dots).

Writes brand/icon.png (256), brand/icon@2x.png (512) and the same art as
brand/logo.png / brand/logo@2x.png. Requires Pillow.

Run from the repository root:  python3 tools/make_icon.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "custom_components" / "polestar_data_portal" / "brand"

BG_TOP = (30, 41, 72)
BG_BOTTOM = (12, 18, 38)
GAUGE_TRACK = (58, 72, 112)
GAUGE_FILL = (64, 200, 214)
BOLT = (255, 255, 255)
DOT = (255, 196, 61)

SS = 4  # supersampling factor
SIZE = 512 * SS


def render() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # Vertical gradient background inside a rounded square.
    grad = Image.new("RGBA", (SIZE, SIZE))
    gd = ImageDraw.Draw(grad)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        gd.line(
            [(0, y), (SIZE, y)],
            fill=tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)) + (255,),
        )
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=int(SIZE * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    cx = cy = SIZE // 2
    radius = int(SIZE * 0.34)
    width = int(SIZE * 0.065)
    box = [cx - radius, cy - radius, cx + radius, cy + radius]

    # Gauge: 270° track (gap at the bottom) with ~75 % filled.
    start, sweep = 135, 270
    d.arc(box, start, start + sweep, fill=GAUGE_TRACK, width=width)
    d.arc(box, start, start + sweep * 0.75, fill=GAUGE_FILL, width=width)
    for angle in (start, start + sweep * 0.75):  # round caps
        a = math.radians(angle)
        px, py = cx + radius * math.cos(a) - width / 2 + width / 2, cy + radius * math.sin(a)
        r = width / 2
        color = GAUGE_FILL
        d.ellipse([px - r, py - r, px + r, py + r], fill=color)
    a = math.radians(start + sweep)
    px, py = cx + radius * math.cos(a), cy + radius * math.sin(a)
    d.ellipse([px - width / 2, py - width / 2, px + width / 2, py + width / 2], fill=GAUGE_TRACK)

    # Lightning bolt.
    s = SIZE / 512
    bolt = [(282, 150), (206, 272), (252, 272), (230, 366), (312, 238), (264, 238), (294, 150)]
    d.polygon([(x * s, y * s) for x, y in bolt], fill=BOLT)

    # Data dots on the open bottom part of the gauge.
    for i, dx in enumerate((-40, 0, 40)):
        r = (9 if i == 1 else 7) * s
        x, y = cx + dx * s, 400 * s
        d.ellipse([x - r, y - r, x + r, y + r], fill=DOT)

    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = render()
    for name, size in (("icon", 256), ("logo", 256)):
        small = big.resize((size, size), Image.LANCZOS)
        small.save(OUT / f"{name}.png", optimize=True)
        big.resize((size * 2, size * 2), Image.LANCZOS).save(OUT / f"{name}@2x.png", optimize=True)
    print("Wrote", ", ".join(sorted(p.name for p in OUT.glob("*.png"))), "to", OUT)


if __name__ == "__main__":
    main()
