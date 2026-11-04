#!/usr/bin/env python3
"""
Process a raw 4x2 generated sheet into production-ready transparent assets.

Usage:
  python3 tools/process_batch.py --src <raw.png> --batch <batch.json> \
      --out-dir public/assets/individual --sheet-out public/assets/sheets/<name>.png

The batch JSON has:
  {
    "start": 9,
    "category": "A — Terrain and Ground",
    "anchor": "tile" | "bottom" | "center",
    "threshold": 0.08,
    "assets": [
      {"slug": "009_light_sandy_ground", "name": "Light sandy ground"},
      ...
    ]
  }

The raw sheet is split into a 4x2 grid. Each cell is keyed by saturation
(the generated backdrop is neutral dark gray), hole-filled, dilated and
feathered. The result is normalized to a 512x384 canvas:
  - tiles: top-face centre at (256,160), 512 px wide
  - bottom-anchored assets: bottom centre at (256,300), fit within 480x300
  - centred assets (UI): centre at (256,192), fit within 420x300
A soft synthetic contact shadow is added to non-UI assets.
"""
import argparse
import json
import os
from collections import deque

import numpy as np
from PIL import Image, ImageFilter


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill interior holes (regions not connected to the border)."""
    h, w = mask.shape
    bg = ~mask
    vis = np.zeros((h, w), dtype=bool)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            if bg[y, x] and not vis[y, x]:
                vis[y, x] = True; dq.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if bg[y, x] and not vis[y, x]:
                vis[y, x] = True; dq.append((y, x))
    while dq:
        y, x = dq.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and bg[ny, nx] and not vis[ny, nx]:
                vis[ny, nx] = True; dq.append((ny, nx))
    return mask | (bg & ~vis)


def largest_component(mask: np.ndarray) -> np.ndarray:
    """Keep only the largest 4-connected component (drops specks)."""
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    best = np.zeros((h, w), dtype=bool)
    best_n = 0
    for y in range(h):
        for x in range(w):
            if mask[y, x] and not seen[y, x]:
                dq = deque([(y, x)])
                seen[y, x] = True
                comp = [(y, x)]
                while dq:
                    cy, cx = dq.popleft()
                    for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                        if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            dq.append((ny, nx))
                            comp.append((ny, nx))
                if len(comp) > best_n:
                    best_n = len(comp)
                    best = np.zeros((h, w), dtype=bool)
                    for yy, xx in comp:
                        best[yy, xx] = True
    return best


def dilate(mask: np.ndarray, radius: int = 2) -> np.ndarray:
    out = mask.copy()
    for _ in range(radius):
        p = np.pad(out, 1, mode='constant', constant_values=False)
        out = (p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:] | out)
    return out


def erode(mask: np.ndarray, radius: int = 2) -> np.ndarray:
    out = mask.copy()
    for _ in range(radius):
        p = np.pad(out, 1, mode='constant', constant_values=True)
        out = (p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:] & out)
    return out


def key_sheet(im: Image.Image, threshold: float = 0.08) -> Image.Image:
    a = np.asarray(im.convert('RGB')).astype(np.float32)
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = (mx - mn) / (mx + 1e-3)
    mask = sat > threshold
    # close small gaps between light pebbles/stones, then fill enclosed holes
    mask = erode(dilate(mask, 3), 3)
    mask = fill_holes(mask)
    mask = largest_component(mask)
    mask = dilate(mask, 1)
    # soften the cutout edge
    alpha = np.asarray(
        Image.fromarray((mask * 255).astype(np.uint8), 'L').filter(ImageFilter.GaussianBlur(1.0))
    ).astype(np.float32) / 255.0
    rgba = np.dstack([a, alpha * 255.0]).astype(np.uint8)
    return Image.fromarray(rgba, 'RGBA')


def add_shadow(canvas: Image.Image, anchor_y: int, width: int) -> Image.Image:
    """Add a soft elliptical contact shadow under a bottom-anchored asset."""
    shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    sw = max(40, int(width * 0.62))
    sh = max(12, int(sw * 0.20))
    cx, cy = canvas.width // 2, anchor_y - sh // 3
    layer = Image.new('RGBA', (sw, sh), (0, 0, 0, 0))
    px = layer.load()
    for y in range(sh):
        for x in range(sw):
            dx = (x - sw / 2) / (sw / 2)
            dy = (y - sh / 2) / (sh / 2)
            d = (dx * dx + dy * dy) ** 0.5
            if d < 1:
                a = int(70 * (1 - d) ** 1.6)
                px[x, y] = (20, 24, 16, a)
    layer = layer.filter(ImageFilter.GaussianBlur(2.2))
    shadow.alpha_composite(layer, (cx - sw // 2, cy - sh // 2))
    canvas.alpha_composite(shadow)
    return canvas


def fit_into(im: Image.Image, box_w: int, box_h: int) -> Image.Image:
    scale = min(box_w / im.width, box_h / im.height)
    return im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--batch', required=True)
    ap.add_argument('--out-dir', default='public/assets/individual')
    ap.add_argument('--sheet-out', required=True)
    ap.add_argument('--sheet-size', default='2048x1024')
    args = ap.parse_args()

    with open(args.batch) as f:
        batch = json.load(f)
    assets = batch['assets']
    assert len(assets) == 8, f'batch must contain exactly 8 assets, got {len(assets)}'
    anchor_mode = batch.get('anchor', 'bottom')
    threshold = float(batch.get('threshold', 0.08))
    category = batch.get('category', '')
    start = int(batch.get('start', 0))

    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(os.path.dirname(args.sheet_out), exist_ok=True)
    cut = key_sheet(Image.open(args.src), threshold)
    W, H = cut.size
    cw, ch = W // 4, H // 2

    sheet_w, sheet_h = (int(x) for x in args.sheet_size.lower().split('x'))
    cell_w, cell_h = sheet_w // 4, sheet_h // 2
    sheet = Image.new('RGBA', (sheet_w, sheet_h), (0, 0, 0, 0))
    manifest = []

    for i, asset in enumerate(assets):
        r, c = divmod(i, 4)
        cell = cut.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch))
        al = np.asarray(cell)[..., 3]
        ys, xs = np.nonzero(al > 40)
        if len(xs) == 0:
            raise RuntimeError(f'empty cell {i + 1} in {args.src}')
        bx0, bx1, by0, by1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        pad = 4
        crop = cell.crop((max(0, bx0 - pad), max(0, by0 - pad),
                          min(cell.width, bx1 + 1 + pad), min(cell.height, by1 + 1 + pad)))

        canvas = Image.new('RGBA', (512, 384), (0, 0, 0, 0))
        if anchor_mode == 'tile':
            # squash to a 2:1 top face and fill the 512 px footprint
            crop = crop.resize((crop.width, max(1, round(crop.height * 0.75))), Image.LANCZOS)
            scale = 512.0 / crop.width
            crop = crop.resize((512, max(1, round(crop.height * scale))), Image.LANCZOS)
            al2 = np.asarray(crop)[..., 3]
            widest = int(np.argmax((al2 > 40).sum(axis=1)))
            canvas.alpha_composite(crop, (256 - crop.width // 2, 160 - widest))
            anchor = (256, 160)
            shadow = False
        elif anchor_mode == 'center':
            crop = fit_into(crop, 420, 300)
            canvas.alpha_composite(crop, (256 - crop.width // 2, 192 - crop.height // 2))
            anchor = (256, 192)
            shadow = False
        else:  # bottom
            crop = fit_into(crop, 480, 300)
            canvas.alpha_composite(crop, (256 - crop.width // 2, 300 - crop.height))
            anchor = (256, 300)
            shadow = True
            canvas = add_shadow(canvas, 300, crop.width)

        slug = asset['slug']
        canvas.save(os.path.join(args.out_dir, slug + '.png'))

        # contact-sheet copy, centred in a cell with 32 px gutters
        sheet_tile = canvas.resize((448, 336), Image.LANCZOS)
        sheet.alpha_composite(sheet_tile, (c * cell_w + (cell_w - 448) // 2,
                                           r * cell_h + (cell_h - 336) // 2))
        manifest.append(dict(id=start + i, name=asset['name'], file=f'individual/{slug}.png',
                             category=category, canvas='512x384',
                             anchor=f'{anchor[0]},{anchor[1]}',
                             source_cell=[c + 1, r + 1]))
        print(f'{start + i:03d} {asset["name"]:36s} bbox={crop.size} anchor={anchor}')

    sheet.save(args.sheet_out)
    print(f'wrote {args.sheet_out} ({sheet_w}x{sheet_h}) and {len(assets)} tiles')
    out_manifest = args.batch.replace('.json', '_manifest.json')
    with open(out_manifest, 'w') as f:
        json.dump(dict(sheet=args.sheet_out, sheet_size=f'{sheet_w}x{sheet_h}',
                       grid='4 columns x 2 rows', tile_canvas='512x384',
                       category=category, assets=manifest), f, indent=2)
    print(f'wrote {out_manifest}')


if __name__ == '__main__':
    main()
