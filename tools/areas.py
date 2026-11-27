"""Area finder (spec 002 R2 / NIN-7): closed areas from ANY drawing style. Uses shapely (installed).

Every way of drawing becomes one planar network: lines, open/closed polylines (with arcs), arcs, circles, hatch
boundaries. Endpoints closer than the gap tolerance are joined, lines are split where they cross, and every closed
area is extracted:
  * explicit areas  = shapes drawn closed (closed polyline, circle, hatch - with its islands as holes)
  * cell areas      = areas closed only by loose linework (4 lines, open polylines meeting, mixed), i.e. cells of
                      the network that are not already covered by an explicit area
Nesting (an area inside another) is recorded as `parent`; what it means (separate object or hole) is decided later
from labels / profile (D4). The drawing is split into VIEWS (plans, sections, elevations sit side by side in model
space) by spatial clustering + nearby view titles, so section linework can never become a plan object.

Usage: python tools/areas.py <project> [--geometry data/<p>/geometry_object.tsv] [--view-gap 1.0] [--plot]
Output: data/<project>/areas.json (metres, every area with its source and metrics) + a printed report.
"""
import argparse
import collections
import functools
import json
import math
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))
import geom  # noqa: E402
import dwg_inventory as inv  # noqa: E402
from shapely import STRtree  # noqa: E402
from shapely.geometry import LineString, Point, Polygon, box  # noqa: E402
from shapely.ops import nearest_points, polygonize, unary_union  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIEW_KIND = [('section', r'разрез|сечение|section|schnitt'),
             ('elevation', r'фасада|изглед|elevation|ansicht|view'),
             ('plan', r'план|plan|grundriss|етаж|floor')]


def _key(p, q):
    return (round(p[0] / q), round(p[1] / q))


def _poly(path):
    pts = [tuple(p) for p in path]
    if len(pts) > 1 and math.dist(pts[0], pts[-1]) < 1e-9:
        pts = pts[:-1]
    if len(pts) < 3:
        return None
    pg = Polygon(pts)
    if not pg.is_valid:
        pg = pg.buffer(0)
    return pg if not pg.is_empty and pg.area > 0 else None


def split_entities(ents, tol):
    """-> explicit [(polygon, entity)], lines [(LineString, entity)], skipped Counter"""
    explicit, lines, skipped = [], [], collections.Counter()
    for e in ents:
        t = e['type']
        if t == 'LWPOLYLINE' and e['paths'] and len(e['paths'][0]) >= 2:
            pts = e['paths'][0]
            nearly = len(pts) > 3 and math.dist(pts[0], pts[-1]) <= tol
            if e.get('closed') or nearly:
                pg = _poly(pts)
                if pg is not None:
                    explicit.append((pg, e))
                    continue
            lines.append((LineString(pts), e))
        elif t in ('LINE', 'ARC') and e['paths']:
            if len(e['paths'][0]) >= 2 and LineString(e['paths'][0]).length > 0:
                lines.append((LineString(e['paths'][0]), e))
        elif t == 'CIRCLE' and e['paths']:
            pg = _poly(e['paths'][0])
            if pg is not None:
                explicit.append((pg, e))
        elif t == 'HATCH':
            loops = [p for p in (_poly(l) for l in e['paths']) if p is not None]
            if loops:   # even-odd fill: islands become holes
                pg = functools.reduce(lambda a, b: a.symmetric_difference(b), loops)
                if not pg.is_empty:
                    explicit.append((pg, e))
                    continue
            skipped['HATCH (no usable boundary)'] += 1
        else:
            skipped[t] += 1
    return explicit, lines, skipped


def close_gaps(noded_lines, tol, report_max):
    """Dangling endpoints: join to the nearest geometry within tol; report bigger gaps up to report_max."""
    segs = list(noded_lines.geoms) if hasattr(noded_lines, 'geoms') else [noded_lines]
    q = tol / 100
    deg = collections.Counter()
    for s in segs:
        c = s.coords
        deg[_key(c[0], q)] += 1
        deg[_key(c[-1], q)] += 1
    tree = STRtree(segs)
    connectors, too_big, dangles, joined = [], [], [], set()
    for s in segs:
        for end in (s.coords[0], s.coords[-1]):
            if deg[_key(end, q)] != 1:
                continue
            p = Point(end)
            best, bd = None, None
            for i in tree.query(p.buffer(report_max)):
                other = segs[i]
                if other is s:
                    continue
                d = other.distance(p)
                if d > 1e-9 and (bd is None or d < bd):
                    best, bd = other, d
            if bd is not None and bd <= tol:
                tgt = nearest_points(best, p)[0].coords[0]
                pair = frozenset((_key(end, q), _key(tgt, q)))
                if pair not in joined:            # two facing dangling ends are one gap, not two
                    joined.add(pair)
                    connectors.append(LineString([end, tgt]))
            elif bd is not None and bd <= report_max:
                too_big.append({'at': end, 'gap': bd})
            else:
                dangles.append(end)
    return connectors, too_big, dangles


def find_areas(ents, tol, report_max, min_area):
    explicit, lines, skipped = split_entities(ents, tol)
    network = [ls for ls, _ in lines] + [pg.exterior for pg, _ in explicit] + \
              [r for pg, _ in explicit if isinstance(pg, Polygon) for r in pg.interiors]
    for pg, _ in explicit:      # multipolygons from hatches
        if not isinstance(pg, Polygon):
            for part in pg.geoms:
                network.append(part.exterior)
                network.extend(part.interiors)
    raw_len = sum(g.length for g in network)
    noded = unary_union(network)
    overlap_len = max(0.0, raw_len - noded.length)
    connectors, too_big, dangles = close_gaps(noded, tol, report_max)
    if connectors:
        noded = unary_union([noded] + connectors)
    cells = [c for c in polygonize(noded) if c.area >= min_area]

    ex_polys = [pg for pg, _ in explicit]
    ex_tree = STRtree(ex_polys) if ex_polys else None
    areas = []
    for pg, e in explicit:
        areas.append({'kind': f"explicit:{e['type'].lower()}", 'geom': pg, 'layers': [e['layer']], 'handles': [e['handle']]})
    covered = 0
    for c in cells:
        if ex_tree is not None:
            hit = [i for i in ex_tree.query(c) if ex_polys[i].buffer(tol).contains(c)]
            if hit:
                covered += 1
                continue
        areas.append({'kind': 'cell', 'geom': c, 'layers': [], 'handles': []})

    # layers of the linework that bounds each cell (for the report and later classification)
    line_geoms = [ls for ls, _ in lines]
    if line_geoms:
        lt = STRtree(line_geoms)
        for a in areas:
            if a['kind'] == 'cell':
                ring = a['geom'].exterior.buffer(tol)
                found = collections.Counter(lines[i][1]['layer'] for i in lt.query(ring) if ring.intersects(line_geoms[i]))
                a['layers'] = [l for l, _ in found.most_common()]
    # nesting: smallest other area whose outline contains this one
    outlines = [Polygon(a['geom'].exterior) if isinstance(a['geom'], Polygon) else a['geom'].convex_hull for a in areas]
    ot = STRtree(outlines)
    for i, a in enumerate(areas):
        rp = a['geom'].representative_point()
        cands = [j for j in ot.query(rp) if j != i and outlines[j].area > a['geom'].area and outlines[j].contains(rp)]
        a['parent'] = min(cands, key=lambda j: outlines[j].area) if cands else None
    report = {'entities_used': len(explicit) + len(lines), 'explicit_shapes': len(explicit), 'loose_lines': len(lines),
              'cells_found': len(cells), 'cells_covered_by_explicit': covered,
              'gaps_joined': len(connectors), 'gaps_too_big': too_big, 'dangling_ends': len(dangles),
              'dangling_examples': dangles[:20], 'overlapping_line_length': overlap_len, 'skipped': dict(skipped)}
    return areas, report


def find_views(areas, texts, gap, title_dist):
    """Cluster areas into views; name each view by the nearest view title."""
    if not areas:
        return [], []
    blobs = unary_union([box(*a['geom'].bounds).buffer(gap / 2) for a in areas])
    blobs = list(blobs.geoms) if hasattr(blobs, 'geoms') else [blobs]
    views = [{'id': f'V{i + 1}', 'geom': b.buffer(-gap / 2) if b.buffer(-gap / 2).area > 0 else b, 'titles': []}
             for i, b in enumerate(sorted(blobs, key=lambda g: (-g.bounds[3], g.bounds[0])))]
    for t in texts:
        p = Point(t['at'])
        d, v = min(((vw['geom'].distance(p), vw) for vw in views), key=lambda x: x[0])
        if d <= title_dist:
            v['titles'].append({'text': t['text'], 'distance': round(d, 3)})
    level_rx = re.compile(r'(?:кота|kote|level|ниво)\s*(?:±|%%[pP]|[+\-])?\s*(\d+[.,]\d{1,3})', re.I)
    for v in views:
        v['titles'].sort(key=lambda t: t['distance'])
        lv = {m.group(0) for t in v['titles'] if re.search(r'план|plan', t['text'], re.I)
              for m in [level_rx.search(t['text'])] if m}
        v['warning'] = (f'probably several plans merged (titles with levels {sorted(lv)}): use a smaller --view-gap'
                        if len(lv) > 1 else None)
        v['kind'] = 'unknown'
        for t in v['titles']:
            for kind, pat in VIEW_KIND:
                if re.search(pat, t['text'], re.I):
                    v['kind'] = kind
                    break
            if v['kind'] != 'unknown':
                break
    vt = STRtree([v['geom'] for v in views])
    owner = []
    for a in areas:
        rp = a['geom'].representative_point()
        hits = [i for i in vt.query(rp) if views[i]['geom'].buffer(gap / 2).contains(rp)]
        owner.append(views[hits[0]]['id'] if hits else None)
    return views, owner


def view_titles(project, k):
    """Texts in model space that look like view titles (from the inventory dumps)."""
    out = []
    pat = re.compile('|'.join(p for _, p in VIEW_KIND), re.I)
    for path in sorted(glob_inventory(project)):
        for r in inv.load(path):
            if r[0] == '*Model' and r[1] in ('TEXT', 'MTEXT') and len(r) > 7:
                t = inv.clean(r[7])
                if pat.search(t) and len(t) < 120:
                    x, y = (float(v) for v in r[5].split(',')[:2])
                    out.append({'text': t, 'at': (x, y)})
    return out


def glob_inventory(project):
    import glob
    return glob.glob(os.path.join(ROOT, 'data', project, 'inventory', '*.tsv'))


def to_m(geom_obj, k):
    def ring(r):
        return [[round(x * k, 4), round(y * k, 4)] for x, y in r.coords]
    polys = [geom_obj] if isinstance(geom_obj, Polygon) else list(geom_obj.geoms)
    return [{'outline': ring(p.exterior), 'holes': [ring(h) for h in p.interiors]} for p in polys]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('project')
    ap.add_argument('--geometry')
    ap.add_argument('--view-gap', type=float, default=5.0,
                    help='metres of empty space that separates two views (5 m: sparse plans stay whole, '
                         'plans ~20 m apart stay separate; tested on Venelin R4)')
    ap.add_argument('--title-dist', type=float, default=15.0, help='max metres from a view to its title')
    ap.add_argument('--plot', action='store_true', help='also write views/<project>/areas_overview.png')
    ap.add_argument('--plot-view', help='plot only this view id (e.g. V24), with area ids and gaps')
    a = ap.parse_args()
    pdir = os.path.join(ROOT, 'data', a.project)
    pj = json.load(open(os.path.join(pdir, 'project.json'), encoding='utf-8'))
    if not pj.get('confirmed'):
        sys.exit('project.json is not confirmed by the user yet (NIN-6).')
    k = pj['units_to_m']
    tol = pj['gap_tolerance_drawing_units']
    report_max = 10 * tol                  # gaps up to 10x the tolerance are reported as "too big - ask"
    min_area = (0.0001 / k / k)            # slivers below 1 cm2 are noise
    gpath = a.geometry or os.path.join(pdir, 'geometry_object.tsv')
    areas, rep = find_areas(geom.load(gpath), tol, report_max, min_area)
    views, owner = find_views(areas, view_titles(a.project, k), a.view_gap / k, a.title_dist / k)

    out_areas = []
    for i, (ar, vid) in enumerate(zip(areas, owner)):
        g = ar['geom']
        per = g.length
        out_areas.append({'id': f'A{i + 1}', 'view': vid, 'kind': ar['kind'], 'layers': ar['layers'][:4],
                          'handles': ar['handles'], 'parent': f"A{ar['parent'] + 1}" if ar['parent'] is not None else None,
                          'area_m2': round(g.area * k * k, 4), 'perimeter_m': round(per * k, 4),
                          'mean_width_m': round(2 * g.area / per * k, 4) if per else None,
                          'holes': sum(len(p.interiors) for p in ([g] if isinstance(g, Polygon) else g.geoms)),
                          'shape': to_m(g, k)})
    counts = collections.Counter(owner)
    out_views = [{'id': v['id'], 'kind': v['kind'], 'titles': v['titles'][:3], 'areas': counts[v['id']],
                  'warning': v['warning'], 'bbox_m': [round(c * k, 3) for c in v['geom'].bounds]} for v in views]
    for v in out_views:
        if v['warning']:
            print(f"WARNING {v['id']}: {v['warning']}")
    rep_m = dict(rep, gaps_too_big=[{'at_m': [round(c * k, 3) for c in g['at']], 'gap_mm': round(g['gap'] * k * 1000, 1)}
                                    for g in rep['gaps_too_big']],
                 dangling_examples=[[round(c * k, 3) for c in p] for p in rep['dangling_examples']],
                 overlapping_line_length_m=round(rep['overlapping_line_length'] * k, 2),
                 gap_tolerance_mm=pj['gap_tolerance_mm'])
    rep_m.pop('overlapping_line_length')
    json.dump({'project': a.project, 'source': os.path.relpath(gpath, ROOT), 'units_to_m': k, 'report': rep_m,
               'views': out_views, 'areas': out_areas},
              open(os.path.join(pdir, 'areas.json'), 'w', encoding='utf-8'), ensure_ascii=False)

    print(f"areas {len(out_areas)} (explicit {rep['explicit_shapes']}, cells kept {rep['cells_found'] - rep['cells_covered_by_explicit']}) "
          f"in {len(views)} views | gaps joined {rep['gaps_joined']} | gaps too big {len(rep['gaps_too_big'])} | "
          f"dangling ends {rep['dangling_ends']} | overlapping lines {rep_m['overlapping_line_length_m']} m | skipped {rep['skipped']}")
    for v in sorted(out_views, key=lambda v: -v['areas'])[:25]:
        t = v['titles'][0]['text'] if v['titles'] else '-'
        print(f"  {v['id']:4} {v['kind']:9} areas {v['areas']:5}  title: {t[:70]}")
    if a.plot or a.plot_view:
        plot(a.project, out_areas, out_views, a.plot_view, rep_m)


def plot(project, areas, views, only=None, rep=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MPoly
    col = {'plan': '#4c78a8', 'section': '#e45756', 'elevation': '#f58518', 'unknown': '#9d9d9d'}
    kind = {v['id']: v['kind'] for v in views}
    if only:
        areas = [a for a in areas if a['view'] == only]
        views = [v for v in views if v['id'] == only]
        col_area = lambda a: '#f2c14e' if a['kind'] == 'cell' else '#4c78a8'
    else:
        col_area = lambda a: col[kind.get(a['view'], 'unknown')]
    fig, ax = plt.subplots(figsize=(20, 14), dpi=110)
    for a in areas:
        for part in a['shape']:
            ax.add_patch(MPoly(part['outline'], closed=True, fc=col_area(a),
                               ec='black', lw=0.3 if only else 0.15, alpha=0.55 if a['kind'] == 'cell' else 0.85))
            for h in part['holes']:
                ax.add_patch(MPoly(h, closed=True, fc='white', ec='black', lw=0.2))
    if only and rep:
        x0, y0, x1, y1 = views[0]['bbox_m']
        for g in rep['gaps_too_big']:
            if x0 - 1 <= g['at_m'][0] <= x1 + 1 and y0 - 1 <= g['at_m'][1] <= y1 + 1:
                ax.plot(*g['at_m'], 'o', ms=7, mfc='none', mec='red', mew=1.2)
    for v in views:
        x0, y0, x1, y1 = v['bbox_m']
        ax.add_patch(MPoly([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], fill=False, ec=col[v['kind']], lw=0.8, ls='--'))
        t = v['titles'][0]['text'][:40] if v['titles'] else ''
        ax.text(x0, y1, f"{v['id']} {v['kind']} {t}", fontsize=6, va='bottom')
    ax.autoscale(); ax.set_aspect('equal'); ax.axis('off')
    out = os.path.join(ROOT, 'views', project); os.makedirs(out, exist_ok=True)
    fn = os.path.join(out, f'areas_{only}.png' if only else 'areas_overview.png')
    fig.savefig(fn, bbox_inches='tight')
    print('plot:', fn)


if __name__ == '__main__':
    main()
