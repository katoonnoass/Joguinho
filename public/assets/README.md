# Joguinho — Isometric Farm Game Asset Pack

A complete, original 200-asset production starter pack for a charming isometric farming
simulation game. The artwork is a stylized 3D-rendered look with rounded, sculpted shapes,
warm saturated colors, soft upper-left lighting and a cozy countryside mood.

**Current progress: 8 / 200 assets (4%)**

---

## Current batch — 001–008 · Terrain and Ground

| ID | Asset | Individual file | Sheet cell |
|----|-------|-----------------|------------|
| 001 | Clean vibrant grass tile | `individual/001_grass_tile.png` | r1 c1 |
| 002 | Grass with tiny wildflowers | `individual/002_grass_wildflowers.png` | r1 c2 |
| 003 | Grass with clovers | `individual/003_grass_clover.png` | r1 c3 |
| 004 | Dry grass tile | `individual/004_dry_grass.png` | r1 c4 |
| 005 | Empty plowed soil tile | `individual/005_plowed_soil.png` | r2 c1 |
| 006 | Wet cultivated soil tile | `individual/006_wet_cultivated_soil.png` | r2 c2 |
| 007 | Soil with tiny seedlings | `individual/007_seedling_soil.png` | r2 c3 |
| 008 | Mud tile | `individual/008_mud_tile.png` | r2 c4 |

**Style reference sheet:** `sheets/terrain_001-008.png` (2048 × 1024, transparent, 4 × 2 grid).

The sheet is the visual style reference for every subsequent generation. Keep the same camera
angle, light direction, palette, material treatment and level of polish.

---

## Art direction

- Beautiful stylized 3D-rendered appearance, not flat vector and not pixel art.
- Fixed isometric camera with a 2:1 diamond ground grid.
- Rounded, sculpted shapes and friendly, slightly exaggerated proportions for mobile readability.
- Vibrant, warm, saturated colors with a cozy countryside palette.
- Soft light from the upper-left; smooth materials, subtle texture, soft ambient occlusion.
- Clear, recognizable silhouettes with clean outlines and no unwanted cropping.
- Subtle contact shadows only — no scenery, sky, painted backgrounds, watermarks or text.
- Original designs inspired by the general charm of premium casual farming games, not replicas.

## Technical specifications

| Property | Specification |
|---|---|
| Format | PNG with real alpha transparency |
| Sheet | 2048 × 1024, 4 columns × 2 rows, exactly 8 assets per sheet |
| Sheet gutters | 32 px horizontal, clear empty spacing between cells |
| Individual canvas | 512 × 384 px, transparent padding |
| Ground footprint | 128 × 64 units (2:1 isometric diamond), 4× scale = 512 × 256 px |
| Ground anchor | `(256, 160)` — centre of the top-face diamond |
| Tile order | Left → right, top → bottom, exact catalog order |
| Light | Upper-left, consistent across every asset |
| Shadows | Soft contact shadow, no background fill |
| UI icons | The only front-facing 2D assets allowed |

The individual tiles are normalized to a true 2:1 top face and share the same anchor, so they
can be dropped straight onto a tile grid without per-asset offsets.

---

## File structure

```
public/assets/
├── catalog.json                  # full 200-asset catalog, categories and progress
├── manifest.json                 # manifest for the current 001–008 batch
├── README.md                     # this document
├── sheets/
│   └── terrain_001-008.png       # normalized transparent contact sheet (2048×1024)
├── individual/
│   ├── 001_grass_tile.png
│   ├── 002_grass_wildflowers.png
│   ├── 003_grass_clover.png
│   ├── 004_dry_grass.png
│   ├── 005_plowed_soil.png
│   ├── 006_wet_cultivated_soil.png
│   ├── 007_seedling_soil.png
│   └── 008_mud_tile.png
└── source/
    └── terrain_001-008_raw.png   # raw generation, gray background — not for production
```

---

## Preview

Serve the `public/` folder (for example `python3 -m http.server 8000 --directory public`)
and open `/preview.html` for a gallery of the sheet and the individual tiles on a
checkerboard, plus the catalog progress.

## Full catalog

| Category | IDs | Count | Status |
|---|---:|---:|---|
| A — Terrain and Ground | 001–024 | 24 | 8 / 24 |
| B — Farm Crops | 025–054 | 30 | 0 / 30 |
| C — Fruit Trees and Bushes | 055–074 | 20 | 0 / 20 |
| D — Farm Buildings | 075–098 | 24 | 0 / 24 |
| E — Farm Animals | 099–116 | 18 | 0 / 18 |
| F — Tools and Farm Equipment | 117–134 | 18 | 0 / 18 |
| G — Fences and Structures | 135–150 | 16 | 0 / 16 |
| H — Environment Decorations | 151–172 | 22 | 0 / 22 |
| I — Harvestable Items and Products | 173–192 | 20 | 0 / 20 |
| J — Game UI Icons | 193–200 | 8 | 0 / 8 |
| **Total** | **001–200** | **200** | **8 / 200** |

The machine-readable version, including per-asset status and file paths, is in `catalog.json`.

---

## Generation workflow

1. Generate **8 assets per sheet** in a 4-column × 2-row grid, in exact catalog order.
2. Keep each asset fully inside its own equally sized cell with clear empty spacing.
3. Use a transparent background, no numbers, labels, borders or captions inside the artwork.
4. Preserve consistent tile-scale relationships between assets.
5. Use the approved `terrain_001-008.png` sheet as the style reference for all later batches.
6. For individual production assets, generate exactly one asset, centered with transparent
   padding, at the same scale, lighting and camera as the sheet.
7. Never duplicate a design to fill an empty position.

At 8 assets per sheet, the full 200-asset pack requires **25 contact sheets**.

---

## Source and processing notes

- `source/terrain_001-008_raw.png` is the untouched generator output (1456 × 720, gray
  background). It is kept for provenance only.
- The production sheet and individual tiles were derived from the raw generation by:
  - keying out the flat gray background while preserving the soft contact shadow;
  - decontaminating anti-aliased edge pixels;
  - normalizing every tile to a 2:1 top face;
  - scaling to a 512 px-wide footprint and aligning all tiles to the `(256, 160)` anchor;
  - composing the normalized 4 × 2 contact sheet on a transparent 2048 × 1024 canvas.
- The reproducible post-processing script is `tools/process_sheet.py` (requires `numpy`
  and `Pillow`). Run it from the repository root:

```bash
python3 tools/process_sheet.py
```

It reads `public/assets/source/terrain_001-008_raw.png` and rewrites the production sheet,
the eight individual tiles and `manifest.json`.
