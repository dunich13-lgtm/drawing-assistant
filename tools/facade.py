"""Facade elements (NIN-15, building profile): adds them to data/<project>/build.json after build_data.py.

1. Lower roofs: where a floor is bigger than the floor above it, the uncovered part gets a flat roof slab at the
   upper floor's level, as thick as the floor slabs (measured or confirmed).
2. Eaves overhang: the roof outline comes from the roof plan (a plan view titled roof / покрив / Dach ...,
   its elevation linework); it is placed over the building by the same sheet step as the floor plans. The eave band
   (bottom / top) is measured in the facades: the long horizontal line pair just above the top storey's floor.
   Only the ring outside the top storey's walls is built; the sloping roof is a later step.
Nothing is asked: what cannot be measured is left out and reported (facade.json 'notes').

Usage: python tools/facade.py <project>   (re-runnable: replaces its own elements in build.json)
"""
import collections
import json
import os
import re
import statistics
import sys

from shapely.affinity import translate
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

import geom

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOF_WORDS = re.compile(r'покрив|pokriv|roof|dach|tetto|techo|toit|cubierta', re.I)
FACADE_WORDS = re.compile(r'фасад|fasad|facade|façade|elevation|ansicht|prospetto|alzado|изглед', re.I)
MAT = {'roof': ['DWG roof', [150, 110, 95], None], 'eaves': ['DWG eaves', [235, 235, 230], None]}


def footprint(elements, view):
    """Filled outer outline of a floor (walls + openings), courtyards and rooms included."""
    parts = [Polygon(e['outline'], e['holes']).buffer(0) for e in elements
             if e['view'] == view and e['kind'] != 'slab' and not e['kind'].startswith('object:facade')]
    if not parts:
        return Polygon()
    u = unary_union(parts).buffer(0.05, join_style='mitre').buffer(-0.05, join_style='mitre')
    return unary_union([Polygon(p.exterior) for p in getattr(u, 'geoms', [u])])


def polys(g, min_area):
    return [p for p in getattr(g, 'geoms', [g]) if isinstance(p, Polygon) and p.area >= min_area]


def element(eid, view, kind, mat, p, base, top, src_base, src_h):
    return {'id': eid, 'area': None, 'view': view, 'kind': f'object:facade:{kind}', 'layer': mat[0], 'tag': mat[0],
            'mat': mat, 'base': round(base, 4), 'top': round(top, 4),
            'outline': [[round(x, 4), round(y, 4)] for x, y in p.exterior.coords],
            'holes': [[[round(x, 4), round(y, 4)] for x, y in h.coords] for h in p.interiors],
            'base_source': src_base, 'height_source': src_h}


def lines_m(ents, u):
    for e in ents:
        for p in e['paths']:
            for (x1, y1), (x2, y2) in zip(p, p[1:]):
                yield x1 * u, y1 * u, x2 * u, y2 * u


def eave_band(secs, ents, u, floor):
    """Lowest long horizontal line above `floor` in each facade, with the next line <= 0.5 m above it."""
    found = []
    for s in secs:
        if not FACADE_WORDS.search(s['title']) or 'drawing_bbox_m' not in s:
            continue
        x0, y0, x1, y1 = s['drawing_bbox_m']
        ys = collections.Counter()
        for ax, ay, bx, by in lines_m(ents, u):
            if abs(ay - by) < 0.005 and x0 - 0.5 <= min(ax, bx) and max(ax, bx) <= x1 + 0.5 and y0 <= ay <= y1:
                ys[round((ay - s['zero_y_m']) / s['scale'], 2)] += abs(bx - ax)
        long_ = sorted(lv for lv, ln in ys.items() if ln >= 0.6 * (x1 - x0) and lv > floor + 0.05)
        if long_:
            lo = long_[0]
            hi = next((lv for lv in long_[1:] if lv - lo <= 0.5), None)
            xs = [x for ax, ay, bx, by in lines_m(ents, u) if abs(ay - by) < 0.005 and x0 - 0.5 <= min(ax, bx)
                  and max(ax, bx) <= x1 + 0.5 and abs((ay - s['zero_y_m']) / s['scale'] - lo) < 0.006 for x in (ax, bx)]
            found.append((lo, hi, s['id'], (max(xs) - min(xs)) * s['scale']))
    if not found:
        return None
    lo = statistics.median(f[0] for f in found)
    his = [f[1] for f in found if f[1] is not None]
    hi = statistics.median(his) if his else None
    return lo, hi, [f[2] for f in found], [f[3] for f in found]


def main(project):
    pdir = os.path.join(ROOT, 'data', project)
    J = lambda n: json.load(open(os.path.join(pdir, n), encoding='utf-8'))
    b, ar, lm = J('build.json'), J('areas.json'), J('layermap.json')
    secs = J('sections.json')['views'] if os.path.exists(os.path.join(pdir, 'sections.json')) else []
    u = ar['units_to_m']
    els = [e for e in b['elements'] if not e['kind'].startswith('object:facade')]
    views = {v['id']: v for v in b['views']}
    order = sorted(views.values(), key=lambda v: v['base'])
    out, notes = [], []

    # slab thickness, as used for the floor slabs
    t = next((round(e['top'] - e['base'], 4) for e in els if e['kind'] == 'slab'), None)

    # 1. lower roofs
    if t:
        for lo, up in zip(order, order[1:]):
            rest = footprint(els, lo['id']).difference(footprint(els, up['id']).buffer(0.02, join_style='mitre'))
            rest = rest.buffer(-0.6, join_style='mitre').buffer(0.6, join_style='mitre')   # narrower than 1.2 m: outline noise, not a roof
            for i, p in enumerate(polys(rest, 2.0)):
                out.append(element(f"{up['id']}.roof{i + 1}", up['id'], 'roof', MAT['roof'], p, up['base'] - t, up['base'],
                                   f'slab thickness {t} m (as the floor slabs)',
                                   f"part of {lo['id']} not covered by {up['id']}; top = {up['id']} floor {up['base']:+.2f}"))
                notes.append(f"roof over the lower part of {lo['id']}: {p.area:.1f} m2 at {up['base']:+.2f}")

    # 2. eaves overhang from the roof plan
    roles = {k: v['role'] for k, v in lm['layers'].items()}
    gpath = os.path.join(pdir, 'geometry_opening_section_view.tsv')
    ents = [e for e in geom.load(gpath) if roles.get(e['layer']) == 'section_view'] if os.path.exists(gpath) else []
    top = order[-1]
    roof_views = [v for v in ar['views'] if v['kind'] == 'plan' and v['id'] not in views
                  and any(ROOF_WORDS.search(t_['text']) for t_ in v['titles'][:1])]
    band = eave_band(secs, ents, u, top['base']) if ents else None
    if not roof_views:
        notes.append('eaves: no roof plan found (a plan titled roof / покрив) - left out')
    elif not band or band[1] is None:
        notes.append('eaves: no eave band found in the facades - left out')
    else:
        rv = roof_views[0]
        x0, y0, x1, y1 = rv['bbox_m']
        segs = [LineString([(ax, ay), (bx, by)]) for ax, ay, bx, by in lines_m(ents, u)
                if x0 - 1 <= min(ax, bx) and max(ax, bx) <= x1 + 1 and y0 - 1 <= min(ay, by) and max(ay, by) <= y1 + 1
                and (ax, ay) != (bx, by)]
        blob = unary_union([s.buffer(0.03) for s in segs]) if segs else Polygon()
        cand = polys(blob, 4.0)
        roof = Polygon(max(cand, key=lambda p: p.area).exterior).buffer(-0.03, join_style='mitre') if cand else None
        # placement: the top storey's offset + k sheet steps (the plans are laid out at a fixed step)
        fp_top = footprint(els, top['id'])
        moved = [(v['dx'], v['dy']) for v in views.values() if v.get('moved') and not v.get('check') and (v['dx'] or v['dy'])]
        step = min(moved, key=lambda d: d[0] ** 2 + d[1] ** 2) if moved else None
        best = None
        if roof is not None and step and not fp_top.is_empty:
            for k in range(-12, 13):
                dx, dy = top['dx'] + k * step[0], top['dy'] + k * step[1]
                r = translate(roof, dx, dy)
                score = r.intersection(fp_top).area / fp_top.area
                d = r.centroid.distance(fp_top.centroid)
                if best is None or (round(score, 2), -d) > (round(best[0], 2), -best[1]):
                    best = (score, d, dx, dy, k)
        if not best or best[0] < 0.9:
            notes.append(f"eaves: roof plan {rv['id']} could not be placed over {top['id']} - left out")
        else:
            lo_, hi_, where, widths = band
            storey = next((v for v in reversed(order) if v['base'] <= lo_), top)
            # the facades show the real eave edge: when the roof plan outline is consistently wider (gutter line,
            # fascia), inset it to the facade widths
            bx0, by0, bx1, by1 = roof.bounds
            diffs = [min((bx1 - bx0) - w, (by1 - by0) - w, key=abs) for w in widths]
            inset = 0.0
            if diffs and max(diffs) - min(diffs) <= 0.02 and 0.01 < statistics.median(diffs) <= 0.4:
                inset = statistics.median(diffs) / 2
                roof = roof.buffer(-inset, join_style='mitre')
            notes.append(f"eaves: roof plan outline vs facade eave lines: {', '.join(f'{d:+.2f}' for d in diffs)} m"
                         + (f" -> inset {inset:.2f} m per side to match the facades" if inset else
                            ' (kept as drawn in the roof plan)'))
            ring = translate(roof, best[2], best[3]).difference(footprint(els, storey['id']))
            ring = ring.buffer(-0.02, join_style='mitre').buffer(0.02, join_style='mitre')
            for i, p in enumerate(polys(ring, 0.5)):
                out.append(element(f"{storey['id']}.eaves{i + 1}", storey['id'], 'eaves', MAT['eaves'], p, lo_, hi_,
                                   f"eave band {lo_:+.2f}..{hi_:+.2f} measured in the facades {', '.join(where)} (automatic)",
                                   f"roof outline from roof plan {rv['id']} ({rv['titles'][0]['text'][:30]}), placed "
                                   f"{best[4]:+d} sheet steps from {top['id']}, {best[0]:.0%} of the top floor inside it; "
                                   f"only the part outside the walls of {storey['id']}"))
            notes.append(f"eaves: {sum(1 for e in out if 'eaves' in e['kind'])} ring(s) at {lo_:+.2f}..{hi_:+.2f} "
                         f"from roof plan {rv['id']}; the sloping roof is not built yet")

    b['elements'] = els + out
    b['counts']['facade'] = len(out)
    b['counts']['elements'] = len(b['elements'])
    b['facade_notes'] = notes
    json.dump(b, open(os.path.join(pdir, 'build.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump({'elements': [e['id'] for e in out], 'notes': notes},
              open(os.path.join(pdir, 'facade.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'facade elements {len(out)}')
    for n in notes:
        print('  ' + n)


if __name__ == '__main__':
    main(sys.argv[1])
