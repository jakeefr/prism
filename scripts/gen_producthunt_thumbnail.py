"""Generate a 240x240 Product Hunt thumbnail for PRISM.

Run: python scripts/gen_producthunt_thumbnail.py
Output: assets/producthunt-thumbnail.png
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def glow_polygon(draw: ImageDraw.ImageDraw, pts: list, color: tuple) -> None:
    r, g, b = color
    draw.polygon(pts, fill=(r, g, b, 10))
    draw.polygon(pts, outline=(r, g, b, 13), width=14)
    draw.polygon(pts, outline=(r, g, b, 36), width=6)
    draw.polygon(pts, outline=(r, g, b, 242), width=2)


def glow_line(
    draw: ImageDraw.ImageDraw,
    p0: tuple,
    p1: tuple,
    color: tuple,
    wide: int = 12,
    mid: int = 5,
) -> None:
    r, g, b = color
    draw.line([p0, p1], fill=(r, g, b, 18), width=wide)
    draw.line([p0, p1], fill=(r, g, b, 45), width=mid)
    draw.line([p0, p1], fill=(r, g, b, 220), width=2)


def main() -> None:
    W, H = 240, 240
    BG = (13, 17, 23)
    BLUE = (88, 166, 255)

    img = Image.new("RGBA", (W, H), (*BG, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    # --- Triangle ---
    # apex top-center, base roughly at y=132
    apex = (120, 18)
    bl = (62, 134)
    br = (178, 134)
    glow_polygon(draw, [apex, bl, br], BLUE)

    # Apex dot
    ax, ay = apex
    draw.ellipse((ax - 6, ay - 6, ax + 6, ay + 6), fill=(*BLUE, 20))
    draw.ellipse((ax - 3, ay - 3, ax + 3, ay + 3), fill=(*BLUE, 230))

    # --- Incoming white beam (left edge → left face midpoint) ---
    left_mid = ((apex[0] + bl[0]) // 2, (apex[1] + bl[1]) // 2)  # ~(91, 76)
    beam_start = (0, left_mid[1])
    draw.line([beam_start, left_mid], fill=(255, 255, 255, 13), width=14)
    draw.line([beam_start, left_mid], fill=(255, 255, 255, 25), width=6)
    draw.line([beam_start, left_mid], fill=(255, 255, 255, 180), width=2)

    # --- Refracted rays from right-face exit point ---
    exit_pt = ((apex[0] + br[0]) // 2, (apex[1] + br[1]) // 2)  # ~(149, 76)

    rays = [
        ((248, 81,  73),  (240,  28)),   # red   – up-right
        ((209, 134, 22),  (240,  52)),   # orange
        ((210, 153, 34),  (240,  76)),   # yellow – near horizontal
        ((63,  185, 80),  (240, 100)),   # green
        ((88,  166, 255), (240, 122)),   # blue
        ((188, 140, 255), (240, 142)),   # violet – down-right
    ]
    for color, end in rays:
        glow_line(draw, exit_pt, end, color)

    # --- Text ---
    font_bold = ImageFont.truetype(r"C:\Windows\Fonts\consolab.ttf", 38)
    font_tag  = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf",  13)

    # "PRISM"
    prism_text = "PRISM"
    bb = draw.textbbox((0, 0), prism_text, font=font_bold)
    tw = bb[2] - bb[0]
    draw.text(((W - tw) // 2, 152), prism_text, font=font_bold, fill=(230, 237, 243, 255))

    # "session intelligence"
    tag_text = "session intelligence"
    bb2 = draw.textbbox((0, 0), tag_text, font=font_tag)
    tw2 = bb2[2] - bb2[0]
    draw.text(((W - tw2) // 2, 201), tag_text, font=font_tag, fill=(139, 148, 158, 255))

    # --- Save ---
    out = Image.new("RGB", (W, H), BG)
    out.paste(img, mask=img.split()[3])

    out_path = Path(__file__).parent.parent / "assets" / "producthunt-thumbnail.png"
    out.save(str(out_path), optimize=True)
    size_kb = out_path.stat().st_size // 1024
    print(f"Saved {out_path}  ({W}x{H}, {size_kb} KB)")


if __name__ == "__main__":
    main()
