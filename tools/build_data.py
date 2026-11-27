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
        for e in elements:
            o = offsets[e['view']]
            if o['moved']:
                sh = lambda p: [round(p[0] + o['dx'], 4), round(p[1] + o['dy'], 4)]
                e['outline'] = [sh(p) for p in e['outline']]
                e['holes'] = [[sh(p) for p in h] for h in e['holes']]

    vinfo = []
    for v in in_views:
        vv = views[v]
        es = [e for e in elements if e['view'] == v]
        vinfo.append({'id': v, 'title': vv['titles'][0]['text'] if vv['titles'] else '', 'elements': len(es),
                      'base': min(e['base'] for e in es), 'top': max(e['top'] for e in es), **offsets[v]})
    out = {'project': a.project, 'stacked': stack, 'views': vinfo, 'elements': elements, 'excluded': excluded,
           'counts': {'areas_found': len(ar['areas']), 'elements': len(elements), 'excluded': len(excluded),
                      'excluded_by_reason': dict(collections.Counter(x['reason'] for x in excluded))}}
    json.dump(out, open(os.path.join(pdir, 'build.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(f"elements {len(elements)} | excluded {len(excluded)} {out['counts']['excluded_by_reason']} | stacked {stack}")
    for v in sorted(vinfo, key=lambda v: v['base']):
        print(f"  {v['id']:4} {v['base']:+6.2f}..{v['top']:+6.2f}  {v['elements']:4} el  {v['title'][:34]:34} | {v['note']}"
              + (f" (dx {v['dx']:.3f}, dy {v['dy']:.3f})" if v['moved'] else ''))


if __name__ == '__main__':
    main()
