#!/usr/bin/env python3
"""Master catalog for the Joguinho 200-asset isometric farm pack.

Provides:
  ASSETS        -> ordered list of dicts (id, name, slug, category, anchor, footprint)
  make_batch(a, b)  -> batch dict for assets a..b (inclusive, 1-based)
  build_catalog()   -> writes public/assets/catalog.json from file existence

Anchors:
  tile   -> terrain ground tiles, top-face centre at (256,160), 512 px wide
  bottom -> world objects standing on the ground, base at (256,300)
  center -> front-facing UI icons, centre at (256,192)
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IND = os.path.join(ROOT, 'public/assets/individual')

CATS = [
    ('A — Terrain and Ground', 'tile', '1x1 tile (128x64 units)', 1, 24),
    ('B — Farm Crops', 'bottom', '1x1 tile', 25, 54),
    ('C — Fruit Trees and Bushes', 'bottom', '2x2 tiles', 55, 74),
    ('D — Farm Buildings', 'bottom', '2x2–4x4 tiles', 75, 98),
    ('E — Farm Animals', 'bottom', '1x1 tile', 99, 116),
    ('F — Tools and Farm Equipment', 'bottom', 'prop', 117, 134),
    ('G — Fences and Structures', 'bottom', 'connects on tile edges', 135, 150),
    ('H — Environment Decorations', 'bottom', 'prop', 151, 172),
    ('I — Harvestable Items and Products', 'bottom', 'prop', 173, 192),
    ('J — Game UI Icons', 'center', 'UI', 193, 200),
]


def _slug(name: str) -> str:
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in ' -_/':
            out.append('_')
    s = ''.join(out)
    while '__' in s:
        s = s.replace('__', '_')
    return s.strip('_')


def _rows():
    """Yield (id, name, category, anchor, footprint) in catalog order."""
    A = []
    # A — Terrain and Ground (1-24)
    a_names = [
        'Clean vibrant grass tile', 'Grass with tiny wildflowers', 'Grass with clovers',
        'Dry grass tile', 'Empty plowed soil tile', 'Wet cultivated soil tile',
        'Soil with tiny seedlings', 'Mud tile', 'Light sandy ground', 'Gravel ground',
        'Natural stone pavement', 'Straight dirt path', 'Curved dirt path',
        'T-junction dirt path', 'Crossroads dirt path', 'Straight stone path',
        'Curved stone path', 'T-junction stone path', 'Crossroads stone path',
        'Clean shallow water tile', 'Water tile with ripples', 'Straight pond edge',
        'Curved pond edge', 'Raised grassy terrain block',
    ]
    for n in a_names:
        A.append(n)
    # B — Farm Crops (25-54): 10 crops x 3 stages
    crops = ['Wheat', 'Corn', 'Carrot', 'Potato', 'Tomato',
             'Lettuce', 'Strawberry', 'Pumpkin', 'Sunflower', 'Sugar cane']
    stages = ['young seedling', 'growing plant', 'mature harvest-ready']
    for c in crops:
        for s in stages:
            A.append(f'{c} — {s}')
    # C — Fruit Trees and Bushes (55-74)
    trees = ['Apple tree', 'Orange tree', 'Lemon tree', 'Pear tree', 'Peach tree',
             'Cherry tree', 'Coconut palm', 'Banana tree', 'Olive tree', 'Raspberry bush']
    for t in trees:
        A.append(f'{t} — healthy')
        A.append(f'{t} — fruit-bearing')
    # D — Farm Buildings (75-98)
    A += [
        'Small farmhouse', 'Upgraded farmhouse', 'Small red barn', 'Large upgraded barn',
        'Small grain silo', 'Large grain silo', 'Chicken coop', 'Cow stable',
        'Pig shelter', 'Sheep barn', 'Goat shelter', 'Wooden beehive station',
        'Windmill', 'Watermill', 'Rustic bakery', 'Dairy production building',
        'Animal feed mill', 'Tool workshop', 'Preserves and jam kitchen',
        'Fruit juice press', 'Candy production kitchen', 'Farm market stall',
        'Tool storage shed', 'Stone water well',
    ]
    # E — Farm Animals (99-116)
    animals = ['Chicken', 'Cow', 'Pig', 'Sheep', 'Goat', 'Duck']
    acts = ['idle', 'walking', 'eating']
    for an in animals:
        for ac in acts:
            A.append(f'{an} — {ac}')
    # F — Tools and Farm Equipment (117-134)
    A += [
        'Watering can', 'Shovel', 'Garden hoe', 'Garden rake', 'Harvesting sickle',
        'Metal bucket', 'Wooden wheelbarrow', 'Empty wooden cart',
        'Cart loaded with vegetables', 'Small vintage tractor', 'Hay trailer',
        'Hand plow', 'Empty wicker basket', 'Harvest basket', 'Wooden water barrel',
        'Wooden storage crate', 'Stack of grain sacks', 'Stack of hay bales',
    ]
    # G — Fences and Structures (135-150)
    A += [
        'Straight wooden fence', 'Corner wooden fence', 'Wooden fence end piece',
        'Closed wooden gate', 'Open wooden gate', 'Straight white picket fence',
        'Corner white picket fence', 'White picket gate', 'Straight stone fence',
        'Corner stone fence', 'Flower-covered stone wall', 'Decorative flower archway',
        'Small wooden bridge', 'Small stone bridge', 'Wooden outdoor steps',
        'Rustic farm lamp post',
    ]
    # H — Environment Decorations (151-172)
    A += [
        'Large decorative rocks', 'Small pebble cluster', 'Fallen tree log',
        'Chopped tree stump', 'Low green bush', 'Pink flowering bush',
        'Yellow flowering bush', 'Daisy flower patch', 'Tulip flowerbed',
        'Lavender flowerbed', 'Empty ceramic flower pot', 'Flower-filled ceramic pot',
        'Friendly scarecrow', 'Rustic wooden bench', 'Picnic table',
        'Decorative oak tree', 'Decorative pine tree', 'Small stone fountain',
        'Wooden birdhouse', 'Firewood pile', 'Blank wooden signboard',
        'Small decorative pond',
    ]
    # I — Harvestable Items and Products (173-192)
    A += [
        'Harvested wheat bundle', 'Corn cob', 'Fresh carrot', 'Potato', 'Tomato',
        'Lettuce head', 'Strawberry', 'Pumpkin', 'Harvested sunflower',
        'Sugar cane bundle', 'Apple', 'Orange', 'Lemon', 'Pear', 'Chicken egg',
        'Milk bottle', 'Cheese wheel', 'Artisan bread loaf', 'Honey jar', 'Flour sack',
    ]
    # J — Game UI Icons (193-200)
    A += [
        'Gold coin', 'Blue premium gem', 'Energy icon', 'Experience star',
        'Land expansion icon', 'Construction icon', 'Harvest action icon',
        'Delivery order icon',
    ]
    assert len(A) == 200, len(A)
    return A


def _meta(i: int):
    for cat, anchor, foot, lo, hi in CATS:
        if lo <= i <= hi:
            return cat, anchor, foot
    raise KeyError(i)


ASSETS = []
for _i, _name in enumerate(_rows(), start=1):
    _cat, _anchor, _foot = _meta(_i)
    ASSETS.append(dict(id=_i, name=_name, slug=f'{_i:03d}' + '_' + _slug(_name),
                       category=_cat, anchor=_anchor, footprint=_foot))


def make_batch(a: int, b: int) -> dict:
    """Batch dict for assets a..b (inclusive, 1-based); must be exactly 8."""
    sel = ASSETS[a - 1:b]
    assert len(sel) == 8, f'batch {a}-{b} has {len(sel)} assets'
    anchors = {x['anchor'] for x in sel}
    assert len(anchors) == 1, f'mixed anchors in {a}-{b}: {anchors}'
    return dict(start=a, category=sel[0]['category'], anchor=sel[0]['anchor'],
                threshold=0.08,
                assets=[dict(slug=x['slug'], name=x['name']) for x in sel])


def done_ids() -> set:
    ids = set()
    for f in glob.glob(os.path.join(IND, '*.png')):
        base = os.path.basename(f)
        try:
            ids.add(int(base[:3]))
        except ValueError:
            pass
    return ids


def build_catalog() -> dict:
    done = done_ids()
    out = []
    for x in ASSETS:
        row = dict(x)
        row['status'] = 'done' if x['id'] in done else 'pending'
        if row['status'] == 'done':
            row['file'] = f'individual/{x["slug"]}.png'
        out.append(row)
    data = dict(
        pack='Joguinho — Isometric Farm Game Asset Pack',
        total_assets=200,
        generated=len(done),
        sheet_size='2048x1024',
        grid='4 columns x 2 rows, 8 assets per sheet',
        tile_canvas='512x384',
        anchors={'tile': '256,160', 'bottom': '256,300', 'center': '256,192'},
        ground_footprint='128x64 units (2:1 isometric diamond)',
        style_reference='sheets/terrain_001-008.png',
        categories=[dict(name=c, anchor=a, count=hi - lo + 1, first=lo, last=hi,
                         done=len([i for i in range(lo, hi + 1) if i in done]))
                    for c, a, f, lo, hi in CATS],
        assets=out,
    )
    path = os.path.join(ROOT, 'public/assets/catalog.json')
    with open(path, 'w') as fh:
        json.dump(data, fh, indent=2)
    return data


def write_batch(a: int, b: int, path: str) -> None:
    with open(path, 'w') as fh:
        json.dump(make_batch(a, b), fh, indent=2)
    print(f'wrote {path} for assets {a}-{b}')


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 4 and sys.argv[1] == 'batch':
        write_batch(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
    else:
        d = build_catalog()
        print(f"catalog: {d['generated']}/{d['total_assets']} done")
        for c in d['categories']:
            print(f"  {c['name']:36s} {c['done']:3d}/{c['count']:3d}")
