"""Heights from sections and facades (spec 002 R3 part 2 / NIN-9, decisions D6, D7). Stdlib + geom.

1. Level marks: every text / attribute that reads like a level ("%%P0.00", "±0.00", "+2.80", "-2.60") in model space.
2. Calibration: marks are grouped into vertical COLUMNS (same x within 0.5 m, no y gap > 15 m). A column is a
   level scale when >= 3 marks fit  level = a*y + b  within 1 cm. Each calibrated column is named by the nearest
   section / facade title (РАЗРЕЗ, ФАСАДА, SECTION, ELEVATION ...); columns with the same title and the same fit
   form one VIEW. Columns that don't fit (mixed rows, stair levels in plans) are reported and not used.
3. Floor levels per view = its marks (used by heights.py as source 2). 4. Opening CANDIDATES (unverified, not used):
   closed rectangles on the section-linework
   and opening layers inside the view (outermost of nested frames), with sill/head levels from the calibration
   and the floor below -> sill/head above floor; typical values per view.
Output: data/<project>/sections.json, used by tools/heights.py as height source 2.

Usage: python tools/sections.py <project> [--geometry data/<p>/geometry_opening_section_view.tsv]
"""
import argparse
import collections
import glob
import json
import math
import os
import re
import statistics
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))
import dwg_inventory as inv  # noqa: E402
import geom  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PM = r'(?:±|%%[pP]|\+/-)'
MARK = re.compile(r'^\s*(' + PM + r'|[+\-])\s*(\d{1,3}[.,]\d{2,3})\s*(?:m|м)?\s*$')
TITLE = re.compile(r'разрез|сечение|фасада|изглед|section|elevation|schnitt|ansicht', re.I)


def mark_value(text):
    m = MARK.match(text)
    if not m:
        return None
    return float(m.group(2).replace(',', '.')) * (-1.0 if m.group(1).strip() == '-' else 1.0)


def fit(pts):
    """least squares level = a*y + b; returns a, b, max residual"""
    n = len(pts)
    my = sum(y for y, _ in pts) / n
    mv = sum(v for _, v in pts) / n
    sxx = sum((y - my) ** 2 for y, _ in pts)
    if sxx == 0:
        return None, None, math.inf
    a = sum((y - my) * (v - mv) for y, v in pts) / sxx
    b = mv - a * my
    return a, b, max(abs(a * y + b - v) for y, v in pts)


def columns(marks, x_tol, y_gap):
    """marks: [(x, y, value, src)] -> list of columns (lists of marks)"""
    out = []
    for m in sorted(marks, key=lambda m: m[0]):
        for c in out:
            if abs(c[0][0] - m[0]) <= x_tol:
                c.append(m)
                break
        else:
            out.append([m])
    split = []
    for c in out:                                  # split a column where the marks have a big vertical gap
        c.sort(key=lambda m: m[1])
        cur = [c[0]]
        for m in c[1:]:
            if m[1] - cur[-1][1] > y_gap:
                split.append(cur)
                cur = [m]
            else:
                cur.append(m)
        split.append(cur)
    return split


def calibrate(cols, titles, k, tol_m, title_dist):
    views, rejected = {}, []
    for c in cols:
        uniq = {(round(m[1], 3), m[2]) for m in c}
        if len(uniq) < 3:
            continue
        a, b, res = fit(list(uniq))
        x = sum(m[0] for m in c) / len(c)
        ys = [m[1] for m in c]
        if a is None or a <= 0 or res > tol_m:
            rejected.append({'x_m': round(x * k, 2), 'marks': len(uniq), 'max_residual_mm': None if res == math.inf else round(res * 1000),
                             'levels': sorted({m[2] for m in c})})
            continue
        centre = (x, (min(ys) + max(ys)) / 2)
        cand = sorted((math.dist(centre, t['at']), t['text']) for t in titles)
        name = cand[0][1] if cand and cand[0][0] <= title_dist else f'untitled level scale at x {x * k:.1f} m'
        key = (name, round(a, 6), round(b, 3))
        v = views.setdefault(key, {'title': name, 'scale_m_per_unit': a, 'zero_y': -b / a, 'columns': [], 'marks': set(),
                                   'x_range': [math.inf, -math.inf], 'y_range': [math.inf, -math.inf], 'residual_mm': 0.0,
                                   'title_distance_m': round(cand[0][0] * k, 1) if cand else None})
        v['columns'].append(round(x * k, 2))
        v.setdefault('columns_x_raw', []).append(x)
        v['marks'] |= {m[2] for m in c}
        v['x_range'] = [min(v['x_range'][0], x), max(v['x_range'][1], x)]
        v['y_range'] = [min(v['y_range'][0], min(ys)), max(v['y_range'][1], max(ys))]
        v['residual_mm'] = max(v['residual_mm'], round(res * 1000, 1))
    return list(views.values()), rejected


def drawing_clusters(ents, gap):
    """group entities into drawings (facades, sections) by spatial proximity -> [(bbox, [ents])]"""
    from shapely.geometry import box
    from shapely.ops import unary_union
    items = []
    for e in ents:
        pts = [p for path in e['paths'] for p in path]
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            items.append(((min(xs), min(ys), max(xs), max(ys)), e))
    blobs = unary_union([box(*b).buffer(gap / 2) for b, _ in items])
    blobs = list(blobs.geoms) if hasattr(blobs, 'geoms') else [blobs]
    groups = [[] for _ in blobs]
    for b, e in items:
        c = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        for i, bl in enumerate(blobs):
            if bl.bounds[0] <= c[0] <= bl.bounds[2] and bl.bounds[1] <= c[1] <= bl.bounds[3]:
                groups[i].append(e)
                break
    return [(bl.bounds, g) for bl, g in zip(blobs, groups) if g]


def facade_openings(view, clusters, k, tol, max_dist):
    """The drawing next to this level scale -> close its linework (area finder) -> window/door-sized rectangles
    (outermost of nested frames) -> sill/head levels from the calibration."""
    import areas as area_finder
    a = view['scale_m_per_unit']
    lvl = lambda y: a * (y - view['zero_y'])
    cx = sum(view['columns_x_raw']) / len(view['columns_x_raw'])
    vy0, vy1 = view['y_range']
    best = None
    for bb, g in clusters:                    # overlapping the scale vertically, nearest horizontally
        if bb[3] < vy0 - 1.0 / k or bb[1] > vy1 + 1.0 / k:
            continue
        d = 0 if bb[0] <= cx <= bb[2] else min(abs(cx - bb[0]), abs(cx - bb[2]))
        if d <= max_dist and (best is None or d < best[0]):
            best = (d, bb, g)
    if best is None:
        return [], {}, None
    _, bb, g = best
    found, _ = area_finder.find_areas(g, tol, 10 * tol, (0.01 / k) ** 2)
    rects = []
    for ar in found:
        pg = ar['geom']
        bx0, by0, bx1, by1 = pg.bounds
        w, h = (bx1 - bx0) * k, (by1 - by0) * a
        if 0.4 <= w <= 4.0 and 0.5 <= h <= 3.4 and pg.area >= 0.9 * (bx1 - bx0) * (by1 - by0):   # rectangle-like
            rects.append((bx0, by0, bx1, by1, (ar['layers'] or ['?'])[0]))
    outer = [r for r in rects if not any(o is not r and o[0] <= r[0] + 1e-6 and o[1] <= r[1] + 1e-6 and o[2] >= r[2] - 1e-6
                                         and o[3] >= r[3] - 1e-6 and (o[2] - o[0]) * (o[3] - o[1]) > (r[2] - r[0]) * (r[3] - r[1])
                                         for o in rects)]
    outer = list({(round(r[0], 1), round(r[1], 1), round(r[2], 1), round(r[3], 1)): r for r in outer}.values())
    floors = sorted(view['marks'])
    out = []
    for bx0, by0, bx1, by1, layer in outer:
        sill, head = lvl(by0), lvl(by1)
        if any(sill + 0.05 < f < head - 0.05 for f in floors):
            continue          # crosses a floor level: a wall panel between two floors' windows, not an opening
        below = [f for f in floors if f <= sill + 0.05]
        floor = max(below) if below else None
        out.append({'x_m': [round(bx0 * k, 3), round(bx1 * k, 3)], 'width_m': round((bx1 - bx0) * k, 3),
                    'sill': round(sill, 3), 'head': round(head, 3), 'floor': floor,
                    'sill_above_floor': round(sill - floor, 3) if floor is not None else None,
                    'head_above_floor': round(head - floor, 3) if floor is not None else None,
                    'kind': 'door' if floor is not None and sill - floor < 0.10 else 'window', 'layer': layer})
    typ = {}
    for kind in ('window', 'door'):
        xs = [o for o in out if o['kind'] == kind and o['sill_above_floor'] is not None]
        if xs:
            typ[kind] = {'n': len(xs), 'sill_above_floor': round(statistics.median(o['sill_above_floor'] for o in xs), 3),
                         'head_above_floor': round(statistics.median(o['head_above_floor'] for o in xs), 3)}
    return out, typ, [round(c * k, 2) for c in bb], g


def plot_view(project, v, g, k):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(16, 8), dpi=110)
    for e in g:
        for p in e['paths']:
            ax.plot([q[0] * k for q in p], [q[1] * k for q in p], lw=0.3, color='#888')
    for o in v['opening_candidates']:
        y0 = o['sill'] + v['zero_y_m']; y1 = o['head'] + v['zero_y_m']
        x0, x1 = o['x_m']
        ax.add_patch(plt.Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, ec='red' if o['kind'] == 'window' else 'blue', lw=1.2))
    for lv in v['levels']:
        ax.axhline(lv + v['zero_y_m'], color='green', lw=0.5, ls='--')
    ax.set_aspect('equal'); ax.set_title(f"{v['id']} {v['title']}  (red window, blue door, green floor levels)")
    out = os.path.join(ROOT, 'views', project); os.makedirs(out, exist_ok=True)
    fn = os.path.join(out, f"section_{v['id']}.png"); fig.savefig(fn, bbox_inches='tight'); print('plot:', fn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('project')
    ap.add_argument('--geometry')
    ap.add_argument('--title-dist', type=float, default=30.0, help='max metres from a level scale to its title')
    ap.add_argument('--plot', help='comma-separated view ids to draw with their openings, e.g. S10,S4')
    a = ap.parse_args()
    pdir = os.path.join(ROOT, 'data', a.project)
    pj = json.load(open(os.path.join(pdir, 'project.json'), encoding='utf-8'))
    k = pj['units_to_m']
    marks, titles = [], []
    for path in glob.glob(os.path.join(pdir, 'inventory', '*.tsv')):
        for r in inv.load(path):
            if len(r) > 7 and r[0] in ('*Model', '*SUB') and r[1] in ('TEXT', 'MTEXT', 'ATTRIB'):
                t = inv.clean(r[7])
                x, y = (float(c) for c in r[5].split(',')[:2])
                v = mark_value(t)
                if v is not None:
                    marks.append((x, y, v, f'{r[2]}:{r[3]}'))
                elif r[0] == '*Model' and r[1] != 'ATTRIB' and TITLE.search(t) and len(t) < 70:
                    titles.append({'text': t, 'at': (x, y)})
    cols = columns(marks, 0.5 / k, 15.0 / k)
    views, rejected = calibrate(cols, titles, k, 0.01, a.title_dist / k)

    gpath = a.geometry or os.path.join(pdir, 'geometry_opening_section_view.tsv')
    ents = geom.load(gpath) if os.path.exists(gpath) else []
    clusters = drawing_clusters(ents, 2.0 / k) if ents else []
    tol = pj['gap_tolerance_drawing_units']
    out_views = []
    for i, v in enumerate(sorted(views, key=lambda v: (v['title'], v['x_range'][0]))):
        ops, typ, dbb, g = facade_openings(v, clusters, k, tol, 8.0 / k) if clusters else ([], {}, None, [])
        out_views.append({'id': f'S{i + 1}', 'title': v['title'], 'levels': sorted(v['marks']),
                          'scale': round(v['scale_m_per_unit'] / k, 4), 'zero_y_m': round(v['zero_y'] * k, 3),
                          'residual_mm': v['residual_mm'], 'columns_x_m': v['columns'], 'drawing_bbox_m': dbb,
                          'title_distance_m': v['title_distance_m'], 'opening_candidates': ops, 'typical_candidates': typ,
                          'openings_note': 'UNVERIFIED: closed window-sized rectangles in this view (can be balcony or wall panels); not used as heights'})
        if a.plot and out_views[-1]['id'] in a.plot.split(','):
            plot_view(a.project, out_views[-1], g, k)
    json.dump({'project': a.project, 'views': out_views, 'rejected_columns': rejected, 'marks_found': len(marks)},
              open(os.path.join(pdir, 'sections.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'level marks {len(marks)} | calibrated level scales {len(out_views)} | rejected columns {len(rejected)}')
    for v in out_views:
        t = '; '.join(f"{kk} n={x['n']} sill +{x['sill_above_floor']:.2f} head +{x['head_above_floor']:.2f}" for kk, x in v['typical_candidates'].items())
        print(f"  {v['id']:4} {v['title'][:32]:32} levels {v['levels']} scale {v['scale']} resid {v['residual_mm']} mm | opening candidates (unverified) {len(v['opening_candidates'])}")
    for r in rejected[:8]:
        print(f"  rejected column at x {r['x_m']} m: {r['marks']} marks, residual {r['max_residual_mm']} mm, levels {r['levels'][:8]}")


if __name__ == '__main__':
    main()
