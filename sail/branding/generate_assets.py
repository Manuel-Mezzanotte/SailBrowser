#!/usr/bin/env python3

# Copyright 2026 The Sail Authors
# You can use, redistribute, and/or modify this source code under
# the terms of the GPL-3.0 license that can be found in the LICENSE file.
"""Generates every Sail icon and logo from the sail glyph.

The glyph geometry in this file is the single source of truth for the logo.
Outputs land in sail/resources/ and are committed, so a normal build never
runs this script. Re-run it only after changing the logo:

    python3 sail/branding/generate_assets.py

Requires ImageMagick (`magick`), Xcode (`actool`, `iconutil`) and a prepared
source tree in build/src (for compile_car.py and the wordmark font).
"""

import argparse
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'sail' / 'resources'
SRC = ROOT / 'build' / 'src'
HELIUM_ASSETS = ROOT / 'resources' / 'assets'
HELIUM_DMG_BACKGROUND = ROOT / 'resources' / 'dmg_background.png'
COMPILE_CAR = SRC / 'tools' / 'mac' / 'icons' / 'compile_car.py'
# Roboto is Apache-2.0 licensed and ships with the Chromium source tree.
FONT = SRC / 'third_party' / 'skia' / 'resources' / 'fonts' / 'Roboto-Regular.ttf'

# Tile colours: gradient top, gradient bottom, and a flat colour for places
# that cannot draw gradients.
PALETTES = {
    'nero': ('#2A2A2C', '#050505', '#0A0A0A'),
    'blu-notte': ('#1E2B47', '#070B14', '#0B1426'),
}
PALETTE = 'blu-notte'

GLYPH = '#FFFFFF'
INK = '#0A0A0A'
MONO = '#3C4043'  # Same grey as Helium's product_logo_22_mono.png.
SAIL_BULGE_DEG = 14
# Apple's icon grid: a 1024 canvas with an 824 tile whose corners are 185.4.
APPLE_MARGIN = 100
RADIUS_RATIO = 185.4 / 824


def mast_segments(x, top, width, bottom):
    r = width / 2
    k = r * 0.5523
    return [
        ('M', (x + r, top)),
        ('C', (x + r + k, top), (x + width, top + r - k), (x + width, top + r)),
        ('L', (x + width, bottom - r)),
        ('C', (x + width, bottom - r + k), (x + r + k, bottom), (x + r, bottom)),
        ('C', (x + r - k, bottom), (x, bottom - r + k), (x, bottom - r)),
        ('L', (x, top + r)),
        ('C', (x, top + r - k), (x + r - k, top), (x + r, top)),
        ('Z',),
    ]


def sail_segments(luff_x, top, bottom, width, radii):
    """Mainsail: straight luff along the mast, evenly bowed leech, flat foot."""
    height = bottom - top
    phi = math.atan2(height, width)
    bulge = math.radians(SAIL_BULGE_DEG)
    start_angle = phi - bulge
    end_angle = min(phi + bulge, math.radians(89))
    handle = math.hypot(width, height) / 3
    u0 = (math.cos(start_angle), math.sin(start_angle))
    u1 = (math.cos(end_angle), math.sin(end_angle))
    head, clew, tack = (luff_x, top), (luff_x + width, bottom), (luff_x, bottom)
    r_head, r_clew, r_tack = radii
    d_head = r_head / math.tan((math.pi / 2 - start_angle) / 2)
    d_clew = r_clew / math.tan(end_angle / 2)
    return [
        ('M', (head[0], head[1] + d_head)),
        ('Q', head, (head[0] + d_head * u0[0], head[1] + d_head * u0[1])),
        ('C', (head[0] + handle * u0[0], head[1] + handle * u0[1]),
         (clew[0] - handle * u1[0], clew[1] - handle * u1[1]),
         (clew[0] - d_clew * u1[0], clew[1] - d_clew * u1[1])),
        ('Q', clew, (clew[0] - d_clew, clew[1])),
        ('L', (tack[0] + r_tack, tack[1])),
        ('Q', tack, (tack[0], tack[1] - r_tack)),
        ('Z',),
    ]


def glyph(mast_x, mast_width, gap, sail_width, top, bottom, radii):
    return (mast_segments(mast_x, top, mast_width, bottom) +
            sail_segments(mast_x + mast_width + gap, top, bottom, sail_width, radii))


# The master glyph on a 1024 canvas. macOS 26+ draws every size from it,
# Finder's list view included, so the gap is wide enough to stay open at
# 32 px. The glyph sits slightly right of centre because a sail carries its
# visual weight near the mast.
GLYPH_SEGMENTS = glyph(270, 64, 60, 382, 140, 840, radii=(10, 14, 14))
GLYPH_BOX = (270, 140, 776, 840)  # left, top, right, bottom

# Below 64 px the master blurs mast and sail into one shape, so these sizes
# are drawn on the pixel grid: whole-pixel mast, gap and sail edges.
PIXEL_GLYPHS = {
    16: glyph(4, 1, 1, 5, 3, 12, radii=(0.2, 0.3, 0.3)),
    22: glyph(5, 2, 2, 9, 2, 20, radii=(0.3, 0.4, 0.4)),
    32: glyph(9, 2, 2, 10, 7, 25, radii=(0.3, 0.5, 0.5)),
}
# The new tab favicon fills the whole 16/32 px square, like Chromium's other
# favicons, with a heavier mast than the app icon so it reads at tab size.
FAVICON_GLYPHS = {
    16: glyph(3, 2, 1, 8, 1, 15, radii=(0.3, 0.4, 0.4)),
    32: glyph(6, 3, 2, 16, 2, 30, radii=(0.5, 0.7, 0.7)),
}
# Chromium's vector icons are drawn at 16-20 dp, so they use the proportions
# of the 32 px design scaled to a 56-unit canvas.
VECTOR_GLYPH = glyph(7.4, 5.8, 5.8, 28.9, 2, 54, radii=(0.6, 0.9, 0.9))


def transform(segments, scale, dx, dy):
    return [(op, *((x * scale + dx, y * scale + dy) for x, y in points))
            for op, *points in segments]


def fmt(value):
    text = f'{value:.2f}'.rstrip('0').rstrip('.')
    return '0' if text == '-0' else text


def svg_path(segments):
    parts = []
    for op, *points in segments:
        coords = ' '.join(f'{fmt(x)} {fmt(y)}' for x, y in points)
        parts.append(f'{op} {coords}' if coords else op)
    return ' '.join(parts)


def vector_icon(segments):
    """Converts path segments to Chromium's .icon vector commands."""
    names = {'M': 'MOVE_TO', 'L': 'LINE_TO', 'Q': 'QUADRATIC_TO', 'C': 'CUBIC_TO'}

    def num(value):
        text = fmt(value)
        return f'{text}f' if '.' in text else text

    lines = []
    for op, *points in segments:
        if op == 'Z':
            lines.append('CLOSE')
        else:
            coords = ', '.join(f'{num(x)}, {num(y)}' for x, y in points)
            lines.append(f'{names[op]}, {coords}')
    return ',\n'.join(lines)


def svg(width, height, body, view_box=None):
    view_box = view_box or f'0 0 {width} {height}'
    return (f'<svg width="{fmt(width)}" height="{fmt(height)}" viewBox="{view_box}" '
            f'fill="none" xmlns="http://www.w3.org/2000/svg">{body}</svg>\n')


def logo_svg(palette):
    """The vector master: tile and glyph on Apple's 1024 grid."""
    top, bottom, _ = palette
    size = 1024 - 2 * APPLE_MARGIN
    glyph_path = transform(GLYPH_SEGMENTS, size / 1024, APPLE_MARGIN, APPLE_MARGIN)
    return svg(1024, 1024,
               f'<defs><linearGradient id="tile" x1="0" y1="0" x2="0" y2="1">'
               f'<stop offset="0" stop-color="{top}"/>'
               f'<stop offset="1" stop-color="{bottom}"/></linearGradient></defs>'
               f'<rect x="{APPLE_MARGIN}" y="{APPLE_MARGIN}" width="{size}" height="{size}" '
               f'rx="{fmt(size * RADIUS_RATIO)}" fill="url(#tile)"/>'
               f'<path d="{svg_path(glyph_path)}" fill="{GLYPH}"/>')


def glyph_only_svg(color, pad=4):
    left, top, right, bottom = GLYPH_BOX
    box = f'{left - pad} {top - pad} {right - left + 2 * pad} {bottom - top + 2 * pad}'
    return svg(right - left + 2 * pad, bottom - top + 2 * pad,
               f'<path d="{svg_path(GLYPH_SEGMENTS)}" fill="{color}"/>', box)


def magick(*args):
    subprocess.run(['magick', *map(str, args)], check=True)


def render(svg_text, out, width, height=None, supersample=4, resize_filter='Lanczos'):
    """Rasterises an SVG to exactly width x height pixels."""
    height = height or width
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / 'in.svg'
        source.write_text(svg_text)
        intrinsic = float(svg_text.split('width="', 1)[1].split('"', 1)[0])
        density = 72 * width * supersample / intrinsic
        magick('-background', 'none', '-density', fmt(density), source,
               '-filter', resize_filter, '-resize', f'{width}x{height}!', out)


def resize(source, out, size):
    magick(source, '-filter', 'Lanczos', '-resize', f'{size}x{size}', out)


def tile_icon_png(out, canvas, tile, glyph_segments, palette, supersample=8):
    """Draws the gradient tile (x, y, size in output pixels) and the glyph, in
    the same pixel coordinates. ImageMagick's SVG renderer ignores gradients,
    so the tile is drawn with ImageMagick primitives instead."""
    x, y, size = tile
    big = canvas * supersample
    tile_px = round(size * supersample)
    radius = fmt(tile_px * RADIUS_RATIO)
    top, bottom, _ = palette
    glyph_svg = svg(canvas, canvas, f'<path d="{svg_path(glyph_segments)}" fill="{GLYPH}"/>')
    with tempfile.TemporaryDirectory() as tmp:
        glyph_png = Path(tmp) / 'glyph.png'
        render(glyph_svg, glyph_png, big, supersample=1)
        magick('-size', f'{big}x{big}', 'xc:none',
               '(', '-size', f'{tile_px}x{tile_px}', f'gradient:{top}-{bottom}',
               '(', '-size', f'{tile_px}x{tile_px}', 'xc:black', '-fill', 'white',
               '-draw', f'roundrectangle 0,0 {tile_px - 1},{tile_px - 1} {radius},{radius}', ')',
               '-alpha', 'off', '-compose', 'CopyOpacity', '-composite', ')',
               '-geometry', f'+{round(x * supersample)}+{round(y * supersample)}',
               '-compose', 'Over', '-composite',
               glyph_png, '-compose', 'Over', '-composite',
               '-filter', 'Box', '-resize', f'{canvas}x{canvas}', out)


def master_icon_png(out, margin, palette):
    """The 1024 icon: tile `margin` px from each edge, master glyph inside."""
    size = 1024 - 2 * margin
    glyph_path = transform(GLYPH_SEGMENTS, size / 1024, margin, margin)
    tile_icon_png(out, 1024, (margin, margin, size), glyph_path, palette, supersample=4)


def pixel_icon_png(out, px, palette, full_bleed):
    """A 16 or 32 px icon drawn on the pixel grid."""
    tile = (0, 0, px) if full_bleed else (px / 16, px / 16, px * 7 / 8)
    tile_icon_png(out, px, tile, PIXEL_GLYPHS[px], palette)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def with_shadow(source, out, blur, offset, opacity=0.30):
    magick(source, '(', '+clone', '-fill', 'black', '-colorize', '100',
           '-channel', 'A', '-evaluate', 'multiply', opacity, '+channel',
           '-blur', f'0x{blur}', ')', '-geometry', f'+0+{offset}',
           '-compose', 'DstOver', '-composite', out)


def build_logo(out, palette):
    write(out / 'logo.svg', logo_svg(palette))
    with tempfile.TemporaryDirectory() as tmp:
        flat = Path(tmp) / 'logo.png'
        master_icon_png(flat, APPLE_MARGIN, palette)
        with_shadow(flat, out / 'logo_1024.png', blur=12, offset=10)


def build_app_icon_assets(assets, logo_png, palette):
    # The macOS 26+ icon: Icon Composer document with a glass glyph layer.
    icon_dir = assets / 'AppIcon.icon'
    write(icon_dir / 'Assets' / 'sail.svg',
          svg(1024, 1024, f'<path d="{svg_path(GLYPH_SEGMENTS)}" fill="currentColor"/>'))
    top, bottom, _ = palette
    p3 = lambda hex_color: 'display-p3:' + ','.join(
        f'{int(hex_color[i:i + 2], 16) / 255:.5f}' for i in (1, 3, 5)) + ',1.00000'
    white = 'srgb:1.00000,1.00000,1.00000,1.00000'
    tile_fill = {'linear-gradient': [p3(top), p3(bottom)]}
    icon_json = {
        'features': ['specular-location'],
        # The tile is already dark, so dark mode keeps the same colours
        # instead of letting macOS replace them with its own grey.
        'fill-specializations': [
            {'value': tile_fill},
            {'appearance': 'dark', 'value': tile_fill},
        ],
        'groups': [{
            'layers': [{
                'fill-specializations': [
                    {'value': {'solid': white}},
                    {'appearance': 'tinted', 'value': {'solid': white}},
                ],
                'glass': True,
                'hidden': False,
                'image-name': 'sail.svg',
                'name': 'sail',
                'opacity-specializations': [
                    {'value': 1},
                    {'appearance': 'dark', 'value': 0.96},
                ],
                'position': {'scale': 1, 'translation-in-points': [0, 0]},
            }],
            'shadow': {'kind': 'neutral', 'opacity': 0.2},
            'specular': 'inside',
            'translucency': {'enabled': False, 'value': 0.5},
        }],
        'supported-platforms': {'squares': 'shared'},
    }
    write(icon_dir / 'icon.json', json.dumps(icon_json, indent=2) + '\n')

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Bitmaps for macOS < 26: pixel designs at 16/32, the master above.
        bitmaps = {}
        for px in (16, 32, 64, 128, 256, 512, 1024):
            bitmaps[px] = tmp / f'icon_{px}.png'
            if px in PIXEL_GLYPHS:
                pixel_icon_png(bitmaps[px], px, palette, full_bleed=False)
            else:
                resize(logo_png, bitmaps[px], px)

        iconset = tmp / 'app.iconset'
        iconset.mkdir()
        for base in (16, 32, 128, 256, 512):
            shutil.copy(bitmaps[base], iconset / f'icon_{base}x{base}.png')
            shutil.copy(bitmaps[base * 2], iconset / f'icon_{base}x{base}@2x.png')
        subprocess.run(['iconutil', '-c', 'icns', '-o', assets / 'app.icns', iconset],
                       check=True)

        # Assets.car = the Icon Composer icon plus the same bitmaps, via actool.
        xcassets = tmp / 'Assets.xcassets'
        appiconset = xcassets / 'AppIcon.appiconset'
        appiconset.mkdir(parents=True)
        shutil.copy(HELIUM_ASSETS / 'Assets.xcassets' / 'Contents.json', xcassets)
        contents = HELIUM_ASSETS / 'Assets.xcassets' / 'AppIcon.appiconset' / 'Contents.json'
        shutil.copy(contents, appiconset)
        for image in json.loads(contents.read_text())['images']:
            px = int(image['filename'].split('_')[1].split('.')[0])
            shutil.copy(bitmaps[px], appiconset / image['filename'])
        shutil.copytree(icon_dir, tmp / 'AppIcon.icon')
        subprocess.run(['python3', COMPILE_CAR, xcassets], check=True)
        shutil.copy(tmp / 'Assets.car', assets / 'Assets.car')


def build_wordmark(out, color, height):
    """Glyph + "Sail", like Helium's 140x32 / 280x64 product_logo.png."""
    scale = height / 64
    glyph_h = round(42 * scale)
    left, top, right, bottom = GLYPH_BOX
    glyph_w = round(glyph_h * (right - left + 8) / (bottom - top + 8))
    baseline = round(52 * scale)
    with tempfile.TemporaryDirectory() as tmp:
        glyph_png = Path(tmp) / 'glyph.png'
        render(glyph_only_svg(color), glyph_png, glyph_w, glyph_h)
        magick('-size', f'{round(140 * scale)}x{height}', 'xc:none',
               glyph_png, '-geometry', f'+{round(4 * scale)}+{baseline - glyph_h}',
               '-composite', '-font', FONT, '-pointsize', round(44 * scale),
               '-fill', color, '-annotate',
               f'+{round(4 * scale) + glyph_w + round(12 * scale)}+{baseline}', 'Sail',
               out)


def build_branding(branding, palette):
    flat = palette[2]
    write(branding / 'product_logo.svg',
          svg(256, 256, f'<rect width="256" height="256" rx="{fmt(256 * RADIUS_RATIO)}" '
                        f'fill="{flat}"/>'
                        f'<path d="{svg_path(transform(GLYPH_SEGMENTS, 0.25, 0, 0))}" '
                        f'fill="{GLYPH}"/>'))

    for name, color in (('product_logo', INK), ('product_logo_white', GLYPH)):
        build_wordmark(branding / f'{name}_200.png', color, 64)
        resize(branding / f'{name}_200.png', branding / f'{name}.png', 140)

    render(svg(22, 22, f'<path d="{svg_path(PIXEL_GLYPHS[22])}" fill="{MONO}"/>'),
           branding / 'product_logo_22_mono.png', 22, supersample=8, resize_filter='Box')

    header = ('// Copyright 2026 The Sail Authors\n'
              '// You can use, redistribute, and/or modify this source code under\n'
              '// the terms of the GPL-3.0 license that can be found in the LICENSE file.\n\n')
    write(branding / 'product_logo.icon',
          header + 'CANVAS_DIMENSIONS, 56,\nFILL_RULE_NONZERO,\n' +
          vector_icon(VECTOR_GLYPH) + '\n')
    argb = ', '.join(f'0x{flat[i:i + 2].upper()}' for i in (1, 3, 5))
    corner = fmt(256 * RADIUS_RATIO)
    corner += 'f' if '.' in corner else ''
    write(branding / 'product_logo_color.icon',
          header + 'CANVAS_DIMENSIONS, 256,\nNEW_PATH,\n'
          f'PATH_COLOR_ARGB, 0xFF, {argb},\n'
          f'ROUND_RECT, 0, 0, 256, 256, {corner},\n'
          'NEW_PATH,\nFILL_RULE_NONZERO,\n'
          'PATH_COLOR_ARGB, 0xFF, 0xFF, 0xFF, 0xFF,\n' +
          vector_icon(transform(GLYPH_SEGMENTS, 0.25, 0, 0)) + '\n')

    raw = branding / 'app_icon' / 'raw.png'
    raw.parent.mkdir(parents=True, exist_ok=True)
    master_icon_png(raw, 0, palette)
    return raw


def build_generated(generated, raw, palette):
    product_icon = generated / 'product_icon'
    product_icon.mkdir(parents=True, exist_ok=True)
    for size in (16, 24, 32, 48, 64, 128, 256):
        out = product_icon / f'{size}x{size}.png'
        if size in PIXEL_GLYPHS:
            pixel_icon_png(out, size, palette, full_bleed=True)
        else:
            resize(raw, out, size)


def build_favicons(favicons):
    """New tab favicon, in the grey of Chromium's favicons. Chromium recolours
    it for dark mode by itself."""
    favicons.mkdir(parents=True, exist_ok=True)
    for size, segments in FAVICON_GLYPHS.items():
        render(svg(size, size, f'<path d="{svg_path(segments)}" fill="{MONO}"/>'),
               favicons / f'favicon_ntp_{size}.png', size, supersample=8, resize_filter='Box')


def build_browser_icon(out, logo_png):
    """Sail's icon for the onboarding's "import from another browser" animation:
    256 px AVIF, with the same margins as the other browsers' icons there."""
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / 'icon.png'
        resize(logo_png, png, 256)
        subprocess.run(['sips', '-s', 'format', 'avif', str(png), '--out', str(out)],
                       check=True, capture_output=True)


def build_onboarding(onboarding, raw, logo_png):
    onboarding.mkdir(parents=True, exist_ok=True)
    resize(raw, onboarding / 'favicon.png', 128)
    build_browser_icon(onboarding / 'browser_icon.avif', logo_png)
    left, top, right, bottom = GLYPH_BOX
    view_box = f'{left - 4} {top - 4} {right - left + 8} {bottom - top + 8}'
    write(onboarding / 'SailLogo.svelte', f'''<!-- Copyright 2026 The Sail Authors. GPL-3.0, see LICENSE. -->
<!-- Generated by sail/branding/generate_assets.py, do not edit by hand. -->
<script lang="ts">
    import type {{ ClassValue }} from "svelte/elements";

    type Props = {{
        height?: string;
        class?: ClassValue;
    }};

    let {{ height = "28px", class: className }}: Props = $props();
</script>

<span class={{["sail-logo", className]}} style:height aria-hidden="true">
    <svg viewBox="{view_box}" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="{svg_path(GLYPH_SEGMENTS)}" fill="currentColor" />
    </svg>
</span>

<style>
    .sail-logo {{
        display: inline-flex;
        color: currentColor;
        flex: 0 0 auto;
        width: auto;
    }}

    .sail-logo svg {{
        display: block;
        width: auto;
        height: 100%;
    }}
</style>
''')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--color', choices=sorted(PALETTES), default=PALETTE,
                        help=f'tile colour (default: {PALETTE})')
    parser.add_argument('--out', type=Path, default=OUT,
                        help='output folder, e.g. to preview another colour')
    args = parser.parse_args()
    palette = PALETTES[args.color]
    out = args.out.resolve()

    for required in (COMPILE_CAR, FONT, HELIUM_DMG_BACKGROUND):
        if not required.exists():
            raise SystemExit(f'missing {required}; prepare the source tree first')

    build_logo(out, palette)
    build_app_icon_assets(out / 'assets', out / 'logo_1024.png', palette)
    raw = build_branding(out / 'branding', palette)
    build_generated(out / 'generated', raw, palette)
    build_favicons(out / 'favicons')
    build_onboarding(out / 'onboarding', raw, out / 'logo_1024.png')
    magick(HELIUM_DMG_BACKGROUND, '-modulate', '100,0', out / 'dmg_background.png')
    print(f'Sail assets ({args.color}) written to {out}')


if __name__ == '__main__':
    main()
