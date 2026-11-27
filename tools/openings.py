"""Openings in plan walls (spec 002 R5 / NIN-11). Drawing-style independent: openings are found as GAPS between
wall ends, not from blocks or schedules (schedules usually don't come with the drawings).

Per plan view: walls = union of its built areas. A morphological closing (mitre buffer out/in by half the widest
opening) bridges every gap; closing minus walls = candidate gaps. A gap is an opening when it is a rectangle,
0.5-3.3 m long, as thick as a wall (6-80 cm), and touches walls at both short ends only.
Kind: the nearest door/window block (layers with role 'opening') within 0.6 m -> door / window; none -> passage.
Sill/head heights (relative to the floor), first source wins:
  1. note or block attribute at the opening (пп=90, H=210 ...)      (none in Venelin R4)
  2. section / facade that draws the opening                         (via sections.py, only if verified)
  3. typical values per project, CONFIRMED by the user once          (data/<p>/openings_answers.json)
  4. ask
Usage: python tools/openings.py <project> [--plot V15]  -> data/<project>/openings.json
       python tools/openings.py <project> --set window.sill=0.9 --set window.head=2.1 --set door.head=2.1 --set passage.head=2.1
"""
import argparse
import collections
import glob
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))
import dwg_inventory as inv  # noqa: E402
from shapely import STRtree  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROPOSAL = {'window': {'sill': 0.90, 'head': 2.10}, 'door': {'sill': 0.0, 'head': 2.10}, 'passage': {'sill': 0.0, 'head': 2.10}}


def poly(shape):
    return Polygon(shape['outline'], shape['holes']).buffer(0)


def wall_ends(walls, min_t, max_t):
    """Short boundary edges of the wall polygons (as long as a wall is thick), with their outward normal."""
    polys = list(walls.geoms) if hasattr(walls, 'geoms') else [walls]
    ends = []
    for p in polys:
        p = p.simplify(0.005)
        for ring in [p.exterior, *p.interiors]:
            c = list(ring.coords)
            for a, b in zip(c, c[1:]):
                L = math.dist(a, b)
                if not (min_t <= L <= max_t):
                    continue
                u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
                m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                n = (-u[1], u[0])
                if walls.contains(Point(m[0] + n[0] * 0.01, m[1] + n[1] * 0.01)):
                    n = (-n[0], -n[1])                       # outward: away from the wall material
                ends.append({'a': a, 'b': b, 'm': m, 'u': u, 'n': n, 'len': L})
    return ends


def find_gaps(walls, max_open=3.3, min_open=0.5, min_t=0.06, max_t=0.8):
    """Openings = pairs of wall ends that face each other across empty space."""
    ends = wall_ends(walls, min_t, max_t)
    if not ends:
        return []
    tree = STRtree([Point(e['m']) for e in ends])
    inner = walls.buffer(-0.005)
    best = {}
    for i, e in enumerate(ends):
        for j in tree.query(Point(e['m']).buffer(max_open + 0.1)):
            if j == i:
                continue
            f = ends[j]
            if e['n'][0] * f['n'][0] + e['n'][1] * f['n'][1] > -0.98:        # must face each other
                continue
            dx, dy = f['m'][0] - e['m'][0], f['m'][1] - e['m'][1]
            s = dx * e['n'][0] + dy * e['n'][1]                                # distance in front of e
            if not (min_open <= s <= max_open):
                continue
            # overlap of the two end edges along e's direction
            pa = sorted(((p[0] - e['m'][0]) * e['u'][0] + (p[1] - e['m'][1]) * e['u'][1]) for p in (e['a'], e['b']))
            pb = sorted(((p[0] - e['m'][0]) * e['u'][0] + (p[1] - e['m'][1]) * e['u'][1]) for p in (f['a'], f['b']))
            ov = min(pa[1], pb[1]) - max(pa[0], pb[0])
            if ov < 0.6 * min(e['len'], f['len']):
                continue
            lateral = abs(dx * e['u'][0] + dy * e['u'][1])                    # both ends on one wall line
            if lateral > 0.05 + abs(e['len'] - f['len']) / 2 or abs(e['len'] - f['len']) > 0.12:
                continue
            rect = Polygon([e['a'], e['b'], f['a'], f['b']]).convex_hull
            if rect.area <= 0 or rect.area < 0.9 * s * min(e['len'], f['len']):  # must be a true rectangle
                continue
            if rect.intersection(inner).area > 0.02 * rect.area:                 # something in between
                continue
            key = tuple(sorted((i, j)))
            if key not in best:
                best[key] = {'geom': rect, 'length': s, 'thickness': (e['len'] + f['len']) / 2, 'axis': e['n']}
    # each wall end belongs to at most one opening: keep the shortest pairing per end
    used, out = set(), []
    for key, g in sorted(best.items(), key=lambda kv: kv[1]['length']):
        if key[0] in used or key[1] in used:
            continue
        used.update(key)
        out.append(g)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('project')
    ap.add_argument('--set', action='append', default=[], help='kind.sill=..., kind.head=... (user-confirmed typical values)')
    ap.add_argument('--plot', help='comma-separated plan view ids to draw')
    a = ap.parse_args()
    pdir = os.path.join(ROOT, 'data', a.project)
    k = json.load(open(os.path.join(pdir, 'project.json'), encoding='utf-8'))['units_to_m']
    lm = json.load(open(os.path.join(pdir, 'layermap.json'), encoding='utf-8'))['layers']
    ar = json.load(open(os.path.join(pdir, 'areas.json'), encoding='utf-8'))
    bd = json.load(open(os.path.join(pdir, 'build.json'), encoding='utf-8'))
    apath = os.path.join(pdir, 'openings_answers.json')
    ans = json.load(open(apath, encoding='utf-8')) if os.path.exists(apath) else {}
    for s in a.set:
        key, _, val = s.partition('=')
        kind, _, what = key.partition('.')
        if kind not in PROPOSAL or what not in ('sill', 'head'):
            sys.exit(f'bad --set {s}')
        ans.setdefault(kind, {})[what] = float(val)
    if a.set:
        json.dump(ans, open(apath, 'w', encoding='utf-8'), indent=1)

    mpath = os.path.join(pdir, 'measured.json')
    measured = json.load(open(mpath, encoding='utf-8')).get('openings', {}) if os.path.exists(mpath) else {}
    disagreements = set()
    door_layers = {n for n, v in lm.items() if v['role'] == 'opening' and any(w in n.lower() for w in ('door', 'врат', 'tür', 'tuer'))}
    open_layers = {n for n, v in lm.items() if v['role'] == 'opening'}
    blocks = []
    for path in glob.glob(os.path.join(pdir, 'inventory', '*.tsv')):
        for r in inv.load(path):
            if r[0] == '*Model' and r[1] == 'INSERT' and r[2] in open_layers and len(r) > 5:
                x, y = (float(c) * k for c in r[5].split(',')[:2])
                blocks.append({'pt': Point(x, y), 'kind': 'door' if r[2] in door_layers else 'window', 'layer': r[2], 'name': r[4]})
    # Doors/windows are often drawn as plain geometry (swing arcs, frame lines), not blocks: use any entity on an
    # opening layer (from the geometry dump) as evidence too, placed at the centre of its bounding box.
    gpath = os.path.join(pdir, 'geometry_opening_section_view.tsv')
    if os.path.exists(gpath):
        import geom
        for e in geom.load(gpath):
            if e['layer'] not in open_layers or e['type'] == 'INSERT':
                continue
            pts = [p for path in e['paths'] for p in path]
            if pts:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                if (max(xs) - min(xs)) * k > 4 or (max(ys) - min(ys)) * k > 4:
                    continue                    # long lines (facade/section linework on these layers) say nothing
                blocks.append({'pt': Point((min(xs) + max(xs)) / 2 * k, (min(ys) + max(ys)) / 2 * k),
                               'kind': 'door' if e['layer'] in door_layers else 'window', 'layer': e['layer'],
                               'name': e['type'].lower()})
    btree = STRtree([b['pt'] for b in blocks]) if blocks else None

    built_views = {v['id']: v for v in bd['views']}
    by_view = collections.defaultdict(list)
    for e in ar['areas']:
        if e['view'] in built_views:
            by_view[e['view']].append(e)
    openings, summary = [], {}
    for vid, es in sorted(by_view.items()):
        walls = unary_union([poly(s) for e in es for s in e['shape']])
        wtree_items = [(poly(s), e) for e in es for s in e['shape']]
        wtree = STRtree([p for p, _ in wtree_items])
        gaps = find_gaps(walls)
        cnt = collections.Counter()
        v = built_views[vid]
        for g in gaps:
            kind, blk = 'passage', None
            if btree is not None:
                near = [blocks[i] for i in btree.query(g['geom'].buffer(0.6)) if g['geom'].distance(blocks[i]['pt']) <= 0.6]
                if near:
                    blk = min(near, key=lambda b: g['geom'].distance(b['pt']))
                    kind = blk['kind']
            sources = {}
            meas_kind = measured.get(kind) or (measured.get('door') if kind == 'passage' else None)
            for what in ('sill', 'head'):
                if kind in ans and what in ans[kind]:          # the user's explicit answer wins
                    sources[what] = (ans[kind][what], f'typical {kind} {what} for this project (confirmed by the user)')
                    if meas_kind and abs(meas_kind[what] - ans[kind][what]) > 0.02:
                        disagreements.add(f"{kind} {what}: user {ans[kind][what]:.2f} vs {meas_kind['source']}")
                elif meas_kind:                                 # measured in the drawing: automatic
                    sources[what] = (meas_kind[what], f"{meas_kind['source']} (automatic)")
                elif what == 'sill' and kind in ('door', 'passage'):
                    sources[what] = (0.0, f'{kind}: starts at the floor')
                else:
                    sources[what] = (None, f'not measurable in the drawing - ask (typical {kind} {what} is often {PROPOSAL[kind][what]:.2f})')
            adj = [wtree_items[i][1] for i in wtree.query(g['geom'].buffer(0.02))]
            layer = collections.Counter((x['layers'] or ['?'])[0] for x in adj).most_common(1)[0][0] if adj else '?'
            outline = [[round(x + (v['dx'] if v['moved'] else 0), 4), round(y + (v['dy'] if v['moved'] else 0), 4)]
                       for x, y in list(g['geom'].exterior.coords)]
            openings.append({'id': f'O{len(openings) + 1}', 'view': vid, 'kind': kind, 'length_m': round(g['length'], 3),
                             'thickness_m': round(g['thickness'], 3), 'wall_layer': layer, 'outline': outline,
                             'block': blk and f"{blk['layer']}:{blk['name']}",
                             'base': v['base'], 'top': v['top'],
                             'sill': sources['sill'][0], 'sill_source': sources['sill'][1],
                             'head': sources['head'][0], 'head_source': sources['head'][1]})
            cnt[kind] += 1
        summary[vid] = dict(cnt)
        if a.plot and vid in a.plot.split(','):
            plot(a.project, vid, walls, [o for o in openings if o['view'] == vid], v)
    resolved = sum(1 for o in openings if o['sill'] is not None and o['head'] is not None)
    missing = sorted({f"{o['kind']}.{w}" for o in openings for w in ('sill', 'head') if o[w] is None})
    json.dump({'project': a.project, 'answers': ans, 'measured': measured, 'proposal': PROPOSAL, 'openings': openings,
               'per_view': summary, 'missing': missing, 'disagreements': sorted(disagreements)},
              open(os.path.join(pdir, 'openings.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    tot = collections.Counter(o['kind'] for o in openings)
    print(f"openings {len(openings)} ({dict(tot)}) | heights resolved {resolved} | opening blocks in drawing {len(blocks)}")
    if missing:
        print('ASK (not measurable in the drawing):', ', '.join(f"{m} (often {PROPOSAL[m.split('.')[0]][m.split('.')[1]]:.2f})" for m in missing))
    for d in sorted(disagreements):
        print('NOTE user answer differs from the drawing:', d)
    for vid, c in summary.items():
        print(f"  {vid:4} {built_views[vid]['title'][:34]:34} {c}")
    lens = collections.Counter((o['kind'], round(o['length_m'], 1)) for o in openings)
    print('most common sizes (kind, length m):', lens.most_common(10))


def plot(project, vid, walls, ops, v):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MP
    col = {'door': '#e45756', 'window': '#4c78a8', 'passage': '#f2a541'}
    fig, ax = plt.subplots(figsize=(20, 11), dpi=110)
    for p in (walls.geoms if hasattr(walls, 'geoms') else [walls]):
        ax.add_patch(MP(list(p.exterior.coords), closed=True, fc='#cfcfcf', ec='black', lw=0.2))
    for o in ops:
        dx, dy = (v['dx'], v['dy']) if v['moved'] else (0, 0)
        ax.add_patch(MP([[x - dx, y - dy] for x, y in o['outline']], closed=True, fc=col[o['kind']], ec='none'))
    ax.autoscale(); ax.set_aspect('equal'); ax.axis('off')
    ax.set_title(f"{vid} {v['title']} - openings: red door, blue window, orange passage (no block)")
    out = os.path.join(ROOT, 'views', project); os.makedirs(out, exist_ok=True)
    fn = os.path.join(out, f'openings_{vid}.png'); fig.savefig(fn, bbox_inches='tight'); print('plot:', fn)


if __name__ == '__main__':
    main()
