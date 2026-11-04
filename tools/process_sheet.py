#!/usr/bin/env python3
"""
Post-process the raw 4x2 terrain sheet (assets 001-008) into production-ready assets.

Input : public/assets/source/terrain_001-008_raw.png  (raw generator output, gray background)
Output: public/assets/sheets/terrain_001-008.png       (2048x1024 transparent contact sheet)
        public/assets/individual/00X_*.png             (512x384 transparent tiles)
        public/assets/manifest.json                    (batch manifest)

Processing:
  1. Key out the flat gray background and soft contact shadow (BFS from the border).
  2. Decontaminate anti-aliased edge pixels.
  3. Squash each tile to a true 2:1 top face.
  4. Scale to a 512 px-wide footprint and align every tile to the (256, 160) anchor.
  5. Compose the normalized 4x2 contact sheet with 32 px gutters.

Requires: numpy, Pillow.
"""
import json
import os
from collections import deque

import numpy as np
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'public/assets/source/terrain_001-008_raw.png')
OUT_SHEET = os.path.join(ROOT, 'public/assets/sheets/terrain_001-008.png')
OUT_IND = os.path.join(ROOT, 'public/assets/individual')
MANIFEST = os.path.join(ROOT, 'public/assets/manifest.json')

# Source-sheet geometry (the raw generator placed the tiles in these bands).
COLS = [(27, 338), (391, 704), (756, 1068), (1119, 1432)]
ROWS = [(86, 295), (446, 654)]

NAMES = [
    ('001_grass_tile', 'Clean vibrant grass tile'),
    ('002_grass_wildflowers', 'Grass with tiny wildflowers'),
    ('003_grass_clover', 'Grass with clovers'),
    ('004_dry_grass', 'Dry grass tile'),
    ('005_plowed_soil', 'Empty plowed soil tile'),
    ('006_wet_cultivated_soil', 'Wet cultivated soil tile'),
    ('007_seedling_soil', 'Soil with tiny seedlings'),
    ('008_mud_tile', 'Mud tile'),
]

SQUASH = 0.75          # 1.5:1 generated diamond -> 2:1 isometric top face
TILE_W, TILE_H = 512, 384
ANCHOR = (256, 160)
SHEET_W, SHEET_H = 2048, 1024
CELL_W, CELL_H = 512, 512
SHEET_TILE_W = 448     # 32 px gutters on each side of a 512 px cell


def key_background(im: Image.Image) -> Image.Image:
    """Return an RGBA copy with the flat gray background removed."""
    a = np.asarray(im.convert('RGB')).astype(np.float32)
    h, w = a.shape[:2]
    bg = np.array([149.0, 149.0, 149.0], dtype=np.float32)

    mx, mn = a.max(axis=2), a.min(axis=2)
    lum = a.mean(axis=2)
    sat = (mx - mn) / (mx + 1e-3)
    dist = np.sqrt(((a - bg) ** 2).sum(axis=2))

    # Neutral pixels are either the flat backdrop or the soft gray contact shadow.
    neutral = (sat < 0.10) & (lum < 218) & (dist < 90)

    # Flood the exterior neutral region from the top-left corner.
    visited = np.zeros((h, w), dtype=bool)
    queue = deque([(0, 0)])
    visited[0, 0] = True
    while queue:
        y, x = queue.popleft()
        if not neutral[y, x]:
            continue
        if y > 0 and not visited[y - 1, x] and neutral[y - 1, x]:
            visited[y - 1, x] = True; queue.append((y - 1, x))
        if y < h - 1 and not visited[y + 1, x] and neutral[y + 1, x]:
            visited[y + 1, x] = True; queue.append((y + 1, x))
        if x > 0 and not visited[y, x - 1] and neutral[y, x - 1]:
            visited[y, x - 1] = True; queue.append((y, x - 1))
        if x < w - 1 and not visited[y, x + 1] and neutral[y, x + 1]:
            visited[y, x + 1] = True; queue.append((y, x + 1))

    background = visited & (lum >= 140)
    shadow = visited & (lum < 140)

    alpha = np.full((h, w), 255.0, dtype=np.float32)
    alpha[background] = 0.0
    shadow_alpha = np.clip((140.0 - lum) / 90.0, 0.0, 1.0) * 0.50
    alpha[shadow] = shadow_alpha[shadow] * 255.0
    alpha = np.asarray(
        Image.fromarray(alpha.astype(np.uint8), 'L').filter(ImageFilter.GaussianBlur(1.0))
    ).astype(np.float32) / 255.0

    af = alpha[..., None]
    rgb = np.where(af > 0.003, (a - (1.0 - af) * bg) / np.maximum(af, 0.003), a)
    rgb = np.clip(rgb, 0, 255)
    rgb[shadow] = np.array([24.0, 24.0, 24.0], dtype=np.float32)
    rgba = np.dstack([rgb, alpha * 255.0]).astype(np.uint8)
    return Image.fromarray(rgba, 'RGBA')


def main() -> None:
    os.makedirs(OUT_IND, exist_ok=True)
    cut = key_background(Image.open(SRC))

    tiles = []
    for r, (y0, y1) in enumerate(ROWS):
        for c, (x0, x1) in enumerate(COLS):
            cell = cut.crop((x0, y0, x1 + 1, y1 + 1))
            al = np.asarray(cell)[..., 3]
            ys, xs = np.nonzero(al > 128)
            bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
            widths = (al > 128).sum(axis=1)
            widest = int(np.argmax(widths))
            idx = r * 4 + c
            slug, display = NAMES[idx]
            tiles.append(dict(cell=cell, bbox=bbox, widest=widest, idx=idx,
                              slug=slug, display=display))
            print(f'{idx + 1:03d} {display:32s} bbox={bbox} widest={widest}')

    sheet = Image.new('RGBA', (SHEET_W, SHEET_H), (0, 0, 0, 0))
    manifest = []
    for t in tiles:
        bx0, by0, bx1, by1 = t['bbox']
        pad = 6
        crop = t['cell'].crop((max(0, bx0 - pad), max(0, by0 - pad),
                               min(t['cell'].width, bx1 + 1 + pad),
                               min(t['cell'].height, by1 + 1 + pad)))
        crop = crop.resize((crop.width, max(1, round(crop.height * SQUASH))), Image.LANCZOS)
        scale = 512.0 / crop.width
        crop = crop.resize((512, max(1, round(crop.height * scale))), Image.LANCZOS)

        al = np.asarray(crop)[..., 3]
        widest = int(np.argmax((al > 128).sum(axis=1)))
        canvas = Image.new('RGBA', (TILE_W, TILE_H), (0, 0, 0, 0))
        canvas.alpha_composite(crop, (ANCHOR[0] - crop.width // 2, ANCHOR[1] - widest))
        canvas.save(os.path.join(OUT_IND, t['slug'] + '.png'))

        r, c = divmod(t['idx'], 4)
        sheet_tile = canvas.resize((SHEET_TILE_W, round(SHEET_TILE_W * TILE_H / TILE_W)), Image.LANCZOS)
        sheet.alpha_composite(sheet_tile, (c * CELL_W + (CELL_W - SHEET_TILE_W) // 2,
                                           r * CELL_H + 88))
        manifest.append(dict(
            id=t['idx'] + 1, name=t['display'], file=f'individual/{t["slug"]}.png',
            category='A — Terrain and Ground', footprint='1x1 tile (128x64 units)',
            canvas='512x384', anchor=f'{ANCHOR[0]},{ANCHOR[1]}',
            source_cell=[c + 1, r + 1]))

    sheet.save(OUT_SHEET)
    with open(MANIFEST, 'w') as f:
        json.dump(dict(
            sheet='sheets/terrain_001-008.png', sheet_size='2048x1024',
            grid='4 columns x 2 rows', tile_canvas='512x384',
            tile_anchor=ANCHOR, style_reference='sheets/terrain_001-008.png',
            assets=manifest), f, indent=2)
    print(f'wrote {OUT_SHEET} ({SHEET_W}x{SHEET_H})')
    print(f'wrote {len(manifest)} individual tiles + {MANIFEST}')


if __name__ == '__main__':
    main()
