"""Build data for SketchUp (spec 002 R4 / NIN-10): areas.json + heights.json -> data/<project>/build.json.

Every RESOLVED buildable area becomes an element: outline + holes (metres), base and top level, layer, view and the
sources of its base and height. Unresolved / skipped areas are listed, never silently dropped.

Stacking (--stack, default for the building profile): plans of different floors are drawn side by side in model
space. Each plan view is moved onto the reference plan (the one at ±0.00, else the largest) by the translation that
best matches the centroids of their explicit shapes (columns, closed outlines) - a vote over all centroid pairs on a
2 cm grid, then counted within 5 cm. A view is only moved when enough of its shapes match; otherwise it stays where
it is drawn and the report says so.

Usage: python tools/build_data.py <project> [--no-stack] [--min-match 0.3]
"""
import argparse
import collections
import json
import math
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def centroid(outline):
    xs, ys = zip(*outline)
    return sum(xs) / len(xs), sum(ys) / len(ys)


def best_offset(ref_pts, pts, grid=0.02, tol=0.05):
    """Translation t with pts + t ~ ref_pts. Returns (t, matched, total)."""
    if not ref_pts or not pts:
        return None, 0, len(pts)
    votes = collections.Counter()
    for rx, ry in ref_pts:
        for x, y in pts:
            votes[(round((rx - x) / grid), round((ry - y) / grid))] += 1
    (gx, gy), _ = votes.most_common(1)[0]
    t = (gx * grid, gy * grid)
    # refine: mean residual of matched pairs
    matched, dx, dy = 0, 0.0, 0.0
    for x, y in pts:
        qx, qy = x + t[0], y + t[1]
        near = min(ref_pts, key=lambda r: (r[0] - qx) ** 2 + (r[1] - qy) ** 2)
        if abs(near[0] - qx) <= tol and abs(near[1] - qy) <= tol:
            matched += 1; dx += near[0] - qx; dy += near[1] - qy
    if matched:
        t = (t[0] + dx / matched, t[1] + dy / matched)
    return t, matched, len(pts)


def footprint_fallback(elements, offsets, ref, failed, min_score):
    """Views whose shapes don't match the reference (different layout, e.g. basement / attic):
    try the sheet step seen in the aligned views (k x step) and bbox alignments; keep the offset with the best
    overlap of the view's footprint with the reference footprint. Marked 'please check'."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    def foot(v):
        return unary_union([Polygon(e['outline'], e['holes']).buffer(0) for e in elements if e['view'] == v])

    ref_f = foot(ref).buffer(0.05)
    steps = {(o['dx'], o['dy']) for o in offsets.values() if o['moved']}
    step = None
    if steps:   # smallest common step, e.g. (0, -40) from (0,-40), (0,-80), (0,-120)
        s = min(steps, key=lambda d: d[0] ** 2 + d[1] ** 2)
        if all(abs(round((dx / s[0]) if s[0] else (dy / s[1])) * s[0] - dx) < 0.05 and
               abs(round((dy / s[1]) if s[1] else (dx / s[0])) * s[1] - dy) < 0.05 for dx, dy in steps):
            step = s
    rb = ref_f.bounds
    for v, m, n, share in failed:
        f = foot(v)
        if f.is_empty:
            continue
        b = f.bounds
        cands = {}
        if step:
            for k in range(-6, 7):
                cands[f'{k} x sheet step {step}'] = (k * step[0], k * step[1])
        cands['left/bottom edges'] = (rb[0] - b[0], rb[1] - b[1])
        cands['right/top edges'] = (rb[2] - b[2], rb[3] - b[3])
        cands['left/top edges'] = (rb[0] - b[0], rb[3] - b[3])
        cands['centres'] = ((rb[0] + rb[2] - b[0] - b[2]) / 2, (rb[1] + rb[3] - b[1] - b[3]) / 2)
        # wall-corner voting: works when only PART of the outline is shared (a bigger basement, a smaller attic)
        def corners(g):
            pts = []
            for p in (g.geoms if hasattr(g, 'geoms') else [g]):
                pts += list(p.simplify(0.01).exterior.coords)[:-1]
            return pts
        rc, vc = corners(ref_f.buffer(-0.05)), corners(f)
        if rc and vc and len(rc) * len(vc) <= 4_000_000:
            votes = collections.Counter((round((x1 - x0) / 0.02), round((y1 - y0) / 0.02)) for x1, y1 in rc for x0, y0 in vc)
            for rank, ((gx, gy), n) in enumerate(votes.most_common(5)):
                cands[f'wall corners #{rank + 1} ({n} corners)'] = (gx * 0.02, gy * 0.02)
        from shapely.affinity import translate
        scored = sorted(((translate(f, dx, dy).intersection(ref_f).area / f.area, name, (dx, dy))
                         for name, (dx, dy) in cands.items()), reverse=True)
        score, name, (dx, dy) = scored[0]
        if score >= min_score:
            offsets[v] = {'dx': round(dx, 4), 'dy': round(dy, 4), 'moved': True, 'check': True,
                          'note': f'aligned to {ref} by footprint ({name}): {score:.0%} of its walls lie on the '
                                  f'reference walls; shapes matched only {m}/{n} - PLEASE CHECK'}
        else:
            offsets[v]['note'] = (f'NOT aligned: shapes {m}/{n}, best footprint overlap {score:.0%} ({name}) - '
                                  f'kept where drawn')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('project')
    ap.add_argument('--no-stack', action='store_true')
    ap.add_argument('--min-match', type=float, default=0.3, help='share of a view\'s explicit shapes that must match to move it')
    ap.add_argument('--confirm-placement', help='view ids whose footprint placement the user confirmed, e.g. V16,V3')
    ap.add_argument('--slab', type=float, help='slab thickness in metres (confirmed by the user)')
    a = ap.parse_args()
    pdir = os.path.join(ROOT, 'data', a.project)
    pj = json.load(open(os.path.join(pdir, 'project.json'), encoding='utf-8'))
    ar = json.load(open(os.path.join(pdir, 'areas.json'), encoding='utf-8'))
    hj = json.load(open(os.path.join(pdir, 'heights.json'), encoding='utf-8'))
    H = hj['areas']
    views = {v['id']: v for v in ar['views']}

    elements, excluded = [], []
    for ar_ in ar['areas']:
        h = H.get(ar_['id'])
        if h is None:
            kind = views.get(ar_['view'], {}).get('kind')
            reason = 'section/elevation view (read for heights, not built)' if kind in ('section', 'elevation') else 'view skipped by the user'
            excluded.append({'id': ar_['id'], 'view': ar_['view'], 'reason': reason})
            continue
        if h['status'] != 'resolved':
            excluded.append({'id': ar_['id'], 'view': ar_['view'], 'reason': 'height or base not resolved'})
            continue
        if pj.get('profile') == 'building' and (ar_.get('mean_width_m') or 0) > 1.0:
            # a wall is never > 1 m thick on average: this is a room / building outline drawn on a wall layer
            excluded.append({'id': ar_['id'], 'view': ar_['view'],
                             'reason': 'too wide for a wall (room or outline drawn on a wall layer)'})
            continue
        for k, part in enumerate(ar_['shape']):
            elements.append({'id': ar_['id'] + (f'.{k + 1}' if len(ar_['shape']) > 1 else ''), 'area': ar_['id'],
                             'view': ar_['view'], 'kind': ar_['kind'], 'layer': (ar_['layers'] or ['?'])[0],
                             'base': h['base'], 'top': h['top'], 'outline': part['outline'], 'holes': part['holes'],
                             'base_source': h['base_source'], 'height_source': h['height_source']})

    # stacking
    in_views = sorted({e['view'] for e in elements})
    offsets = {v: {'dx': 0.0, 'dy': 0.0, 'moved': False, 'note': 'kept where drawn'} for v in in_views}
    stack = not a.no_stack and pj.get('profile') == 'building' and len(in_views) > 1
    if stack:
        anchors = collections.defaultdict(list)
        for e in elements:
            if e['kind'].startswith('explicit'):
                anchors[e['view']].append(centroid(e['outline']))
        base_of = {v: min(e['base'] for e in elements if e['view'] == v) for v in in_views}
        ref = min(in_views, key=lambda v: (abs(base_of[v]), -len(anchors[v])))
        offsets[ref]['note'] = 'reference plan'
        failed = []
        for v in in_views:
            if v == ref:
                continue
            t, m, n = best_offset(anchors[ref], anchors[v])
            share = m / n if n else 0
            if t and share >= a.min_match and m >= 3:
                offsets[v] = {'dx': round(t[0], 4), 'dy': round(t[1], 4), 'moved': True,
                              'note': f'aligned to {ref}: {m}/{n} explicit shapes match within 5 cm ({share:.0%})'}
            else:
                failed.append((v, m, n, share))
        if failed:
            footprint_fallback(elements, offsets, ref, failed, a.min_match)
            # second pass: a view placed in the first pass may reveal the sheet step for the ones still unplaced
            still = [f for f in failed if not offsets[f[0]]['moved']]
            if still and len(still) < len(failed):
                footprint_fallback(elements, offsets, ref, still, a.min_match)
        for e in elements:
            o = offsets[e['view']]
            if o['moved']:
                sh = lambda p: [round(p[0] + o['dx'], 4), round(p[1] + o['dy'], 4)]
                e['outline'] = [sh(p) for p in e['outline']]
                e['holes'] = [[sh(p) for p in h] for h in e['holes']]

    # ---- building profile additions (NIN-11): placement confirmation, opening infill, slabs --------------------
    bpath = os.path.join(pdir, 'building_answers.json')
    bans = json.load(open(bpath, encoding='utf-8')) if os.path.exists(bpath) else {}
    if a.confirm_placement:
        bans['placement_confirmed'] = sorted(set(bans.get('placement_confirmed', [])) | set(a.confirm_placement.split(',')))
    if a.slab is not None:
        bans['slab_thickness_m'] = a.slab
    if a.confirm_placement or a.slab is not None:
        json.dump(bans, open(bpath, 'w', encoding='utf-8'), indent=1)
    # placement the drawing can't tell: the user clicked the same building corner in the reference plan (p1) and in
    # this view (p2) with tools/acad/acad_pick.ps1 -Label align_<view>  ->  offset = p1 - p2
    k = pj['units_to_m']
    for v in in_views:
        pick = os.path.join(pdir, f'acad_pick_align_{v}.json')
        if os.path.exists(pick) and stack:
            pk = json.load(open(pick, encoding='utf-8'))
            inside = lambda p, vid: (lambda b: b[0] - 0.5 <= p[0] * k <= b[2] + 0.5 and b[1] - 0.5 <= p[1] * k <= b[3] + 0.5)(views[vid]['bbox_m'])
            if not (inside(pk['p1'], ref) and inside(pk['p2'], v)):
                print(f"WARNING {os.path.basename(pick)} ignored: click 1 must be in the reference plan {ref} and click 2 in "
                      f"{v} ({views[v]['titles'][0]['text'][:40] if views[v]['titles'] else v}); got "
                      f"{'ok' if inside(pk['p1'], ref) else 'outside'} / {'ok' if inside(pk['p2'], v) else 'outside'}")
                continue
            dx, dy = (pk['p1'][0] - pk['p2'][0]) * k, (pk['p1'][1] - pk['p2'][1]) * k
            old = offsets[v]
            for e in elements:                         # undo an automatic move first, then apply the user's
                if e['view'] == v:
                    sh = lambda p: [round(p[0] - (old['dx'] if old['moved'] else 0) + dx, 4),
                                    round(p[1] - (old['dy'] if old['moved'] else 0) + dy, 4)]
                    e['outline'] = [sh(p) for p in e['outline']]
                    e['holes'] = [[sh(p) for p in h] for h in e['holes']]
            offsets[v] = {'dx': round(dx, 4), 'dy': round(dy, 4), 'moved': True, 'check': False,
                          'note': f'aligned by the user: same corner clicked in both plans ({os.path.basename(pick)})'}
    for v in bans.get('placement_confirmed', []):
        if v in offsets and offsets[v].get('check'):
            offsets[v]['check'] = False
            offsets[v]['note'] = offsets[v]['note'].replace(' - PLEASE CHECK', '') + '; placement confirmed by the user'

    infill = 0
    opath = os.path.join(pdir, 'openings.json')
    if pj.get('profile') == 'building' and os.path.exists(opath):
        for o in json.load(open(opath, encoding='utf-8'))['openings']:
            if o['sill'] is None or o['head'] is None or o['view'] not in offsets:
                continue
            pieces = []
            if o['sill'] > 0.001:
                pieces.append(('sill', o['base'], o['base'] + o['sill'], o['sill_source']))
            if o['base'] + o['head'] < o['top'] - 0.001:
                pieces.append(('lintel', o['base'] + o['head'], o['top'], o['head_source']))
            for name, z0, z1, src in pieces:
                elements.append({'id': f"{o['id']}.{name}", 'area': None, 'view': o['view'], 'kind': f'infill:{o["kind"]}',
                                 'layer': o['wall_layer'], 'base': round(z0, 4), 'top': round(z1, 4),
                                 'outline': o['outline'], 'holes': [],
                                 'base_source': f"{o['kind']} {o['id']} ({o['length_m']} m): {src}",
                                 'height_source': f"wall top of {o['view']}"})
                infill += 1

    # ---- window and door objects in the openings (NIN-13): frame + glass / frame + closed leaf -----------------
    objects = 0
    if pj.get('profile') == 'building' and os.path.exists(opath):
        FW, FD = 0.06, 0.07                     # frame width (face) and depth (across the wall)
        MAT = {'frame': ['DWG window frame', [236, 236, 232], None, 'DWG windows'],
               'glass': ['DWG glass', [150, 190, 220], 0.35, 'DWG glass'],
               'door': ['DWG door', [150, 112, 74], None, 'DWG doors'],
               'dframe': ['DWG door frame', [120, 90, 60], None, 'DWG doors']}
        for o in json.load(open(opath, encoding='utf-8'))['openings']:
            if o['kind'] not in ('window', 'door') or o['sill'] is None or o['head'] is None or o['view'] not in offsets:
                continue
            c = o['outline'][:4]
            sides = [(c[i], c[(i + 1) % 4]) for i in range(4)]
            L = o['length_m']
            # the side whose length matches the opening length runs along the opening
            i0 = min(range(4), key=lambda i: abs(math.dist(*sides[i]) - L))
            A, B = sides[i0]
            D = c[(i0 + 3) % 4]                 # A's other neighbour: across the wall
            Lr, T = math.dist(A, B), math.dist(A, D)
            if Lr < 0.3 or T < 0.03:
                continue
            u = ((B[0] - A[0]) / Lr, (B[1] - A[1]) / Lr)
            w = ((D[0] - A[0]) / T, (D[1] - A[1]) / T)
            def rect(s0, s1, d0, d1):
                pt = lambda s, d: [round(A[0] + u[0] * s + w[0] * (T / 2 + d), 4), round(A[1] + u[1] * s + w[1] * (T / 2 + d), 4)]
                return [pt(s0, d0), pt(s1, d0), pt(s1, d1), pt(s0, d1), pt(s0, d0)]
            z0, zs, zh = o['base'], o['base'] + o['sill'], o['base'] + o['head']
            parts = []
            if o['kind'] == 'window':
                parts = [('jambL', rect(0, FW, -FD / 2, FD / 2), zs, zh, 'frame'),
                         ('jambR', rect(Lr - FW, Lr, -FD / 2, FD / 2), zs, zh, 'frame'),
                         ('bottom', rect(FW, Lr - FW, -FD / 2, FD / 2), zs, zs + FW, 'frame'),
                         ('top', rect(FW, Lr - FW, -FD / 2, FD / 2), zh - FW, zh, 'frame'),
                         ('glass', rect(FW, Lr - FW, -0.01, 0.01), zs + FW, zh - FW, 'glass')]
            else:
                parts = [('jambL', rect(0, FW, -FD / 2, FD / 2), z0, zh, 'dframe'),
                         ('jambR', rect(Lr - FW, Lr, -FD / 2, FD / 2), z0, zh, 'dframe'),
                         ('top', rect(FW, Lr - FW, -FD / 2, FD / 2), zh - FW, zh, 'dframe'),
                         ('leaf', rect(FW, Lr - FW, -0.02, 0.02), z0 + 0.01, zh - FW, 'door')]
            for name, outline, b0, b1, m in parts:
                if b1 - b0 <= 0.005:
                    continue
                mat = MAT[m]
                elements.append({'id': f"{o['id']}.{name}", 'area': None, 'view': o['view'], 'kind': f"object:{o['kind']}",
                                 'layer': mat[3], 'tag': mat[3], 'mat': mat[:3], 'base': round(b0, 4), 'top': round(b1, 4),
                                 'outline': outline, 'holes': [],
                                 'base_source': f"{o['kind']} {o['id']} ({L} m): sill {o['sill_source']}",
                                 'height_source': f"head {o['head_source']}"})
                objects += 1

    slabs = 0
    t = bans.get('slab_thickness_m')
    t_src = f'slab thickness {t} m (confirmed by the user)' if t else None
    mpath = os.path.join(pdir, 'measured.json')
    ms = (json.load(open(mpath, encoding='utf-8')).get('slab_thickness') if os.path.exists(mpath) else None)
    if not t and ms:                                   # measured in the sections: automatic
        t, t_src = ms['value'], f"slab thickness {ms['value']} m, {ms['source']} (automatic)"
    if pj.get('profile') == 'building' and t:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        for v in in_views:
            parts = [Polygon(e['outline'], e['holes']).buffer(0) for e in elements if e['view'] == v]
            if not parts:
                continue
            base = min(e['base'] for e in elements if e['view'] == v and not e['kind'].startswith('infill'))
            shape = unary_union(parts).buffer(0.05, join_style='mitre').buffer(-0.05, join_style='mitre')
            for i, p in enumerate(shape.geoms if hasattr(shape, 'geoms') else [shape]):
                if p.area < 4.0:
                    continue
                elements.append({'id': f'{v}.slab{i + 1}', 'area': None, 'view': v, 'kind': 'slab', 'layer': 'DWG slab',
                                 'base': round(base - t, 4), 'top': base,
                                 'outline': [[round(x, 4), round(y, 4)] for x, y in p.exterior.coords], 'holes': [],
                                 'base_source': f'{t_src}, under the floor level',
                                 'height_source': f'outer outline of the walls and openings of {v}; top = floor level {base:+.2f}'})
                slabs += 1

    vinfo = []
    for v in in_views:
        vv = views[v]
        es = [e for e in elements if e['view'] == v]
        walls = [e for e in es if e['kind'] != 'slab' and not e['kind'].startswith(('infill', 'object:'))] or es
        vinfo.append({'id': v, 'title': vv['titles'][0]['text'] if vv['titles'] else '', 'elements': len(es),
                      'base': min(e['base'] for e in walls), 'top': max(e['top'] for e in walls),   # the floor, not the slab
                      'slab_bottom': min(e['base'] for e in es), **offsets[v]})
    out = {'project': a.project, 'stacked': stack, 'views': vinfo, 'elements': elements, 'excluded': excluded,
           'counts': {'areas_found': len(ar['areas']), 'elements': len(elements), 'infill_pieces': infill, 'slabs': slabs,
                      'window_door_parts': objects,
                      'excluded': len(excluded),
                      'excluded_by_reason': dict(collections.Counter(x['reason'] for x in excluded))}}
    json.dump(out, open(os.path.join(pdir, 'build.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(f"elements {len(elements)} (walls/objects {len(elements) - infill - slabs - objects}, opening infill {infill}, window/door parts {objects}, slabs {slabs}) | "
          f"excluded {len(excluded)} {out['counts']['excluded_by_reason']} | stacked {stack}")
    for v in sorted(vinfo, key=lambda v: v['base']):
        print(f"  {v['id']:4} {v['base']:+6.2f}..{v['top']:+6.2f}  {v['elements']:4} el  {v['title'][:34]:34} | {v['note']}"
              + (f" (dx {v['dx']:.3f}, dy {v['dy']:.3f})" if v['moved'] else ''))


if __name__ == '__main__':
    main()
