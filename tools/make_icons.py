#!/usr/bin/env python3
"""Draws the Path Patrol icons with the standard library only (no Pillow, no image tools).

    python3 tools/make_icons.py [output folder]

Writes (by default into site/icons/): icon.svg, icon-192.png, icon-512.png, icon-maskable-512.png, apple-touch-icon.png.

The picture is the brand mark from the page header: three aqua bars of different heights and opacities, skewed
upwards to the right, on the page's near-black. The PNGs are rendered from the same numbers as the SVG, with
anti-aliasing from a signed-distance function per shape, so the two cannot drift apart. The output is
deterministic: running it again changes no byte.

Three kinds of square:
    any        rounded corners with transparent outside, for browsers and the install dialog
    maskable   full bleed, with the mark inside the central 80 % circle, so any platform mask leaves it whole
    apple      full bleed (iOS rounds it, and fills anything transparent with black)
"""
import math
import pathlib
import struct
import sys
import zlib

BG = (7, 11, 18)               # --bg     #070b12
AQUA = (114, 244, 209)         # --aqua   #72f4d1
SKEW = math.tan(math.radians(18))                # the header mark is skewY(-18deg): the right side rises

# The header mark, in the CSS pixels it is built from: three 7 px bars 3 px apart, bottom aligned, with these heights,
# opacities and a 1 px corner radius.
BARS = [(0, 12, 0.55), (10, 25, 1.0), (20, 18, 0.76)]          # (left, height, opacity)
BAR_W, RADIUS, MARK_W = 7.0, 1.0, 27.0

DESIGN = 512.0
MARK_UNIT = 9.9                # design pixels per CSS pixel: the mark is about 270 x 280 of the 512 square
ROUND = 0.225                  # corner radius of the "any" square, as a share of its side

OUT = pathlib.Path(__file__).resolve().parents[1] / 'site' / 'icons'


def bars():
    """The three bars in design units, centred on the middle of the square: [(x0, x1, y0, y1, radius, opacity)] before the skew."""
    u = MARK_UNIT
    mid_x = MARK_W / 2
    # The skew moves each bar up or down by how far it is from the middle. The mark then spans from the highest top to the
    # lowest bottom, and is centred on that.
    shift = [SKEW * (mid_x - (left + BAR_W / 2)) for left, _, _ in BARS]              # down is +: the left bar goes down, the right one up
    top = min(-h + dy for (_, h, _), dy in zip(BARS, shift))
    bottom = max(dy for dy in shift)
    centre_y = (top + bottom) / 2
    out = []
    for left, h, opacity in BARS:
        out.append(((left - mid_x) * u + DESIGN / 2, (left + BAR_W - mid_x) * u + DESIGN / 2,
                    (-h - centre_y) * u + DESIGN / 2, (0 - centre_y) * u + DESIGN / 2, RADIUS * u, opacity))
    return out


def round_box(px, py, x0, x1, y0, y1, r):
    """Signed distance from a point to a rounded rectangle (negative inside)."""
    cx, cy, hx, hy = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    qx, qy = abs(px - cx) - (hx - r), abs(py - cy) - (hy - r)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def render(size, kind):
    """size x size RGBA bytes."""
    scale = size / DESIGN
    shapes = bars()
    mid_x = DESIGN / 2
    pixels = bytearray(size * size * 4)
    r_bg = ROUND * DESIGN
    for py in range(size):
        y = (py + 0.5) / scale
        for px in range(size):
            x = (px + 0.5) / scale
            # background
            if kind == 'any':
                a = min(1.0, max(0.0, 0.5 - round_box(x, y, 0, DESIGN, 0, DESIGN, r_bg) * scale))
            else:
                a = 1.0
            r, g, b = BG
            alpha = a
            # the bars, skewed: undo the skew so each is an upright rounded box
            y_local = y + SKEW * (x - mid_x)
            for x0, x1, y0, y1, rad, opacity in shapes:
                if x < x0 - 3 or x > x1 + 3:
                    continue
                d = round_box(x, y_local, x0, x1, y0, y1, rad) * scale / math.sqrt(1 + SKEW * SKEW)
                c = min(1.0, max(0.0, 0.5 - d)) * opacity
                if c > 0:
                    r, g, b = r + (AQUA[0] - r) * c, g + (AQUA[1] - g) * c, b + (AQUA[2] - b) * c
            i = (py * size + px) * 4
            pixels[i:i + 4] = bytes((round(r), round(g), round(b), round(alpha * 255)))
    return bytes(pixels)


def png(size, rgba):
    def chunk(tag, data):
        body = tag + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)
    rows = b''.join(b'\x00' + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b''))


def svg():
    """The same picture as vector: a rounded square, and the bars as upright rounded boxes inside a skewed group."""
    shapes = bars()
    body = []
    for x0, x1, y0, y1, rad, opacity in shapes:
        body.append(f'    <rect x="{x0:.2f}" y="{y0:.2f}" width="{x1 - x0:.2f}" height="{y1 - y0:.2f}" rx="{rad:.2f}" opacity="{opacity}"/>')
    origin = f'{DESIGN / 2:g}'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {DESIGN:g} {DESIGN:g}" width="512" height="512">\n'
            f'  <title>Path Patrol</title>\n'
            f'  <rect width="{DESIGN:g}" height="{DESIGN:g}" rx="{ROUND * DESIGN:.1f}" fill="#{BG[0]:02x}{BG[1]:02x}{BG[2]:02x}"/>\n'
            f'  <g fill="#{AQUA[0]:02x}{AQUA[1]:02x}{AQUA[2]:02x}" transform="translate({origin} {origin}) skewY(-18) translate(-{origin} -{origin})">\n'
            + '\n'.join(body) + '\n  </g>\n</svg>\n')


def main():
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    out.mkdir(parents=True, exist_ok=True)
    jobs = [('icon-192.png', 192, 'any'), ('icon-512.png', 512, 'any'), ('icon-maskable-512.png', 512, 'maskable'), ('apple-touch-icon.png', 180, 'apple')]
    (out / 'icon.svg').write_text(svg())
    print('wrote icon.svg')
    for name, size, kind in jobs:
        (out / name).write_bytes(png(size, render(size, kind)))
        print(f'wrote {name} ({size}x{size}, {kind})')


if __name__ == '__main__':
    sys.exit(main())
