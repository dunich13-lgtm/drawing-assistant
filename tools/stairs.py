"""Stairs in 3D (NIN-14). Reads the stair layer (role 'stairs') of every built plan view and finds, per staircase:
  flights   groups of >= 3 parallel tread lines of (nearly) equal length, evenly spaced 0.20-0.40 m
  walk line the longer polyline that runs through the flights; its start is the end nearest a CIRCLE (bottom of the
            stair, drawing convention), else the end away from an arrow head; it gives each flight's up-direction and
            the order of the flights
  notes     "12 ст.18.3/30", "N St. 17,5/28", "N steps ..." -> risers / riser height / going, used as a check
Rise per riser = floor-to-floor of the view / all risers counted in the staircase (each tread line = one riser);
landings are built between consecutive flights at the level reached. Every value carries its source; what the drawing
can't tell (no walk line, no circle/arrow) is reported as a question.
Usage: python tools/stairs.py <project> [--plot V5]  -> data/<project>/stairs.json (used by tools/build_data.py)
"""
import argparse
import collections
import glob
import json
import math
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))
import geom  # noqa: E402
from shapely.geometry import LineString, MultiPoint, Point, Polygon  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTE = re.compile(r'(\d{1,2})\s*(?:ст|st|stufen|steps?|бр)\.?\s*(\d{1,2}(?:[.,]\d)?)\s*/\s*(\d{2}(?:[.,]\d)?)', re.I)


def segments(ents, k):
    """straight 2-point pieces (lines and 2-vertex polylines) in metres, with the entity index"""
    out = []
    for i, e in enumerate(ents):
        if e['type'] in ('LINE', 'LWPOLYLINE') and e['paths']:
            p = e['paths'][0]
            if len(p) == 2:
                a, b = (p[0][0] * k, p[0][1] * k), (p[-1][0] * k, p[-1][1] * k)
                if math.dist(a, b) > 0.3:
                    out.append((a, b, i))
    return out


def fill_missing(f):
    """a tread line hidden by the cut line leaves a double gap: put the missing line(s) back"""
    lines, pos = f['lines'], f['pos']
    g = sorted(b - a for a, b in zip(pos, pos[1:]))[len(pos) // 2 - 1] if len(pos) > 2 else f['going']
    out_l, out_p = [lines[0]], [pos[0]]
    for l, p in zip(lines[1:], pos[1:]):
        gap = p - out_p[-1]
        extra = int(round(gap / g)) - 1 if g > 0 else 0
        for e in range(1, max(0, extra) + 1):
            t = e / (extra + 1)
            prev = out_l[-1]
            out_l.append([(prev[0][0] + (l[0][0] - prev[0][0]) * t, prev[0][1] + (l[0][1] - prev[0][1]) * t),
                          (prev[1][0] + (l[1][0] - prev[1][0]) * t, prev[1][1] + (l[1][1] - prev[1][1]) * t)])
            out_p.append(out_p[-1] + gap * t)
            f['filled'] = f.get('filled', 0) + 1
        out_l.append(l); out_p.append(p)
    f['lines'], f['pos'], f['going'] = out_l, out_p, g
    return f


def merge_split(flights, max_gap=0.7):
    """A flight whose tread lines are cut in two (by the drawing's cut line / break symbol) comes out as two pieces
    in the same column, one after the other: merge them back into one flight."""
    def extent(f):
        ps = [(p[0] - f['m0'][0]) * f['u'][0] + (p[1] - f['m0'][1]) * f['u'][1] for l in f['lines'] for p in l]
        return min(ps), max(ps)
    merged = True
    while merged:
        merged = False
        for i in range(len(flights)):
            for j in range(len(flights)):
                if i == j:
                    continue
                f, g = flights[i], flights[j]
                if abs(f['u'][0] * g['u'][0] + f['u'][1] * g['u'][1]) < 0.99:
                    continue
                # g's lines in f's frame
                gpos = sorted(((l[0][0] + l[1][0]) / 2 - f['m0'][0]) * f['n'][0] + ((l[0][1] + l[1][1]) / 2 - f['m0'][1]) * f['n'][1]
                              for l in g['lines'])
                ge = [(p[0] - f['m0'][0]) * f['u'][0] + (p[1] - f['m0'][1]) * f['u'][1] for l in g['lines'] for p in l]
                fe = extent(f)
                ov = min(fe[1], max(ge)) - max(fe[0], min(ge))
                if ov < 0.5 * min(fe[1] - fe[0], max(ge) - min(ge)):
                    continue
                fpos = sorted(f['pos'])
                gap = min(abs(gpos[0] - fpos[-1]), abs(fpos[0] - gpos[-1]))
                if gap > max_gap:
                    continue
                lines = f['lines'] + g['lines']
                key = lambda l: ((l[0][0] + l[1][0]) / 2 - f['m0'][0]) * f['n'][0] + ((l[0][1] + l[1][1]) / 2 - f['m0'][1]) * f['n'][1]
                lines.sort(key=key)
                f['lines'] = lines
                f['pos'] = [key(l) for l in lines]
                f['width'] = max(f['width'], g['width'])
                f['going'] = (f['pos'][-1] - f['pos'][0]) / (len(f['pos']) - 1)
                f['merged_from_split'] = True
                fill_missing(f)
                flights.pop(j)
                merged = True
                break
            if merged:
                break
    return flights


def flights_from(segs, min_n=3):
    """group parallel equal-length segments that stack at a regular spacing"""
    used, flights = set(), []
    order = sorted(range(len(segs)), key=lambda i: -math.dist(segs[i][0], segs[i][1]))
    for i in order:
        if i in used:
            continue
        a, b, _ = segs[i]
        L = math.dist(a, b)
        u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)          # along the tread
        n = (-u[1], u[0])                                     # across the treads (walking direction, either sign)
        mates = []
        for j in range(len(segs)):
            if j in used:
                continue
            c, d, _ = segs[j]
            Lj = math.dist(c, d)
            v = ((d[0] - c[0]) / Lj, (d[1] - c[1]) / Lj)
            if abs(u[0] * v[0] + u[1] * v[1]) < 0.995 or abs(Lj - L) > 0.12:
                continue
            m = ((c[0] + d[0]) / 2, (c[1] + d[1]) / 2)
            m0 = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            along = (m[0] - m0[0]) * u[0] + (m[1] - m0[1]) * u[1]
            if abs(along) > 0.15:                              # same tread band
                continue
            mates.append(((m[0] - m0[0]) * n[0] + (m[1] - m0[1]) * n[1], j))
        mates.sort()
        # keep the longest run with regular spacing 0.20-0.40 m that contains i (position 0)
        pos = [p for p, _ in mates]
        best = None
        for s in range(len(mates)):
            run = [mates[s]]
            for t in range(s + 1, len(mates)):
                gap = mates[t][0] - run[-1][0]
                if 0.20 <= gap <= 0.40 and (len(run) < 2 or abs(gap - (run[1][0] - run[0][0])) < 0.03):
                    run.append(mates[t])
                elif gap < 0.20:
                    continue
                else:
                    break
            if any(j == i for _, j in run) and len(run) >= min_n and (best is None or len(run) > len(best)):
                best = run
        if best:
            used.update(j for _, j in best)
            going = (best[-1][0] - best[0][0]) / (len(best) - 1)
            m0 = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            lines = [((m0[0] + n[0] * p - u[0] * L / 2, m0[1] + n[1] * p - u[1] * L / 2),
                      (m0[0] + n[0] * p + u[0] * L / 2, m0[1] + n[1] * p + u[1] * L / 2)) for p, _ in best]
            flights.append({'lines': lines, 'width': L, 'going': going, 'u': u, 'n': n, 'pos': [p for p, _ in best],
                            'm0': m0})
    return flights


def walk_line(ents, k, flights):
    """longest non-tread polyline crossing at least one flight; start = end nearest a circle"""
    circles = [(e['center'][0] * k, e['center'][1] * k) for e in ents if e['type'] == 'CIRCLE' and 'center' in e]
    best = None
    for e in ents:
        if e['type'] != 'LWPOLYLINE' or not e['paths'] or e.get('closed'):
            continue
        pts = [(p[0] * k, p[1] * k) for p in e['paths'][0]]
        ls = LineString(pts)
        if ls.length < 1.0:
            continue
        hits = sum(1 for f in flights if ls.intersects(LineString(f['lines'][len(f['lines']) // 2])))
        if hits and (best is None or (hits, ls.length) > (best[0], best[1].length)):
            best = (hits, ls)
    if not best:
        return None, 'no walk line crossing the flights'
    ls = best[1]
    s, e = Point(ls.coords[0]), Point(ls.coords[-1])
    if circles:
        ds = min(s.distance(Point(c)) for c in circles)
        de = min(e.distance(Point(c)) for c in circles)
        if de < ds:
            ls = LineString(list(ls.coords)[::-1])
        return ls, 'walk line starts at the circle (bottom of the stair)'
    return ls, 'walk line direction ASSUMED (no circle at either end)'


def staircases(flights, max_gap=2.5):
    """flights that are close to each other belong to one staircase"""
    groups = []
    for f in flights:
        poly = MultiPoint([p for l in f['lines'] for p in l]).convex_hull
        for g in groups:
            if any(poly.distance(h) < max_gap for h in g['hulls']):
                g['flights'].append(f); g['hulls'].append(poly)
                break
        else:
            groups.append({'flights': [f], 'hulls': [poly]})
    return groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('project')
    ap.add_argument('--plot', help='comma-separated view ids')
    a = ap.parse_args()
    pdir = os.path.join(ROOT, 'data', a.project)
    k = json.load(open(os.path.join(pdir, 'project.json'), encoding='utf-8'))['units_to_m']
    ar = json.load(open(os.path.join(pdir, 'areas.json'), encoding='utf-8'))
    bd = json.load(open(os.path.join(pdir, 'build.json'), encoding='utf-8'))
    gpath = os.path.join(pdir, 'geometry_stairs.tsv')
    if not os.path.exists(gpath):
        sys.exit('no stair geometry: tools\\acad\\acad_geo_dump.ps1 -Project <p> -Roles stairs')
    ents = geom.load(gpath)
    bviews = {v['id']: v for v in bd['views']}
    vbox = {v['id']: v['bbox_m'] for v in ar['views']}

    def view_of(pts):
        x = sum(p[0] for p in pts) / len(pts); y = sum(p[1] for p in pts) / len(pts)
        for vid, b in vbox.items():
            if vid in bviews and b[0] - 1 <= x <= b[2] + 1 and b[1] - 1 <= y <= b[3] + 1:
                return vid
    per_view = collections.defaultdict(list)
    for e in ents:
        pts = [(p[0] * k, p[1] * k) for path in e['paths'] for p in path] or ([(e['pt'][0] * k, e['pt'][1] * k)] if 'pt' in e else [])
        if pts:
            v = view_of(pts)
            if v:
                per_view[v].append(e)

    notes = []
    for path in glob.glob(os.path.join(pdir, 'inventory', '*.tsv')):
        import dwg_inventory as inv
        for r in inv.load(path):
            if r[0] == '*Model' and r[1] in ('TEXT', 'MTEXT') and len(r) > 7:
                m = NOTE.search(inv.clean(r[7]))
                if m:
                    x, y = (float(c) * k for c in r[5].split(',')[:2])
                    notes.append({'risers': int(m.group(1)), 'rise': float(m.group(2).replace(',', '.')) / 100,
                                  'going': float(m.group(3).replace(',', '.')) / 100, 'at': (x, y), 'text': inv.clean(r[7])})

    out, questions, skipped = [], [], []
    plan_levels = sorted(v['base'] for v in bviews.values())
    for vid, es in sorted(per_view.items()):
        v = bviews[vid]
        H = round(v['top'] - v['base'], 4)
        if not any(l > v['base'] + 0.01 for l in plan_levels):
            # the top plan shows the flights ARRIVING from the floor below (drawing convention): nothing goes up from here
            skipped.append(f"{vid} ({v['title'][:30]}): top floor - its stair drawing shows the flights arriving from below")
            continue
        fl = merge_split(flights_from(segments(es, k)))
        for si, g in enumerate(staircases(fl)):
            wl, wl_src = walk_line(es, k, g['flights'])
            steps_total = sum(len(f['lines']) for f in g['flights'])
            # order flights along the walk line, orient each one up the stair
            for f in g['flights']:
                mid = f['lines'][len(f['lines']) // 2]
                c = ((mid[0][0] + mid[1][0]) / 2, (mid[0][1] + mid[1][1]) / 2)
                f['t'] = wl.project(Point(c)) if wl else 0
                if wl:
                    p0 = wl.interpolate(max(0, f['t'] - 0.2)); p1 = wl.interpolate(min(wl.length, f['t'] + 0.2))
                    up = (p1.x - p0.x, p1.y - p0.y)
                    if up[0] * f['n'][0] + up[1] * f['n'][1] < 0:
                        f['lines'] = f['lines'][::-1]
            g['flights'].sort(key=lambda f: f['t'])
            hull = MultiPoint([p for f in g['flights'] for l in f['lines'] for p in l]).convex_hull
            note = min(notes, key=lambda n_: hull.distance(Point(n_['at'])), default=None)
            note = note if note and hull.buffer(0.8).contains(Point(note['at'])) else None   # only a note AT the stair
            counted = steps_total
            if note and note['rise'] > 0:
                # the note's riser height is the designer's number: it decides how many risers the storey needs.
                # Steps above the plan's cut line are usually not drawn: missing ones continue the top flight.
                R = max(1, round(H / note['rise']))
                diff = R - counted
                top = g['flights'][-1]
                if diff > 0 and len(top['lines']) >= 2:
                    l1, l0 = top['lines'][-1], top['lines'][-2]
                    d = (l1[0][0] - l0[0][0], l1[0][1] - l0[0][1])
                    for e in range(1, diff + 1):
                        top['lines'].append([(l1[0][0] + d[0] * e, l1[0][1] + d[1] * e), (l1[1][0] + d[0] * e, l1[1][1] + d[1] * e)])
                    top['added_above_cut'] = diff
                elif diff < 0:
                    top['lines'] = top['lines'][:max(1, len(top['lines']) + diff)]
                steps_total = sum(len(f['lines']) for f in g['flights'])
                rise = H / steps_total
                rise_src = (f"note '{note['text']}' (rise {note['rise']:.3f}) -> {steps_total} risers × {rise:.4f} m for "
                            f"{H:.2f} m; {counted} drawn" + (f", {diff} added above the cut line" if diff > 0 else ''))
            else:
                rise = H / steps_total if steps_total else None
                rise_src = f'floor-to-floor {H:.2f} m / {steps_total} tread lines counted in the plan'
            sc = {'id': f'{vid}.ST{si + 1}', 'view': vid, 'base': v['base'], 'floor_to_floor': H, 'risers': steps_total,
                  'rise': round(rise, 4) if rise else None, 'walk_line': wl_src, 'rise_source': rise_src,
                  'note': note and note['text'], 'flights': []}
            if note:
                sc['note_check'] = f"note '{note['text']}': {steps_total} risers × {rise:.3f} m (drawn {counted})"
            if steps_total != counted:
                sc['check'] = (f"{steps_total - counted:+d} steps vs the drawing ({counted} drawn): added past the drawn end "
                               f"(steps above the cut line) - PLEASE CHECK")
            if not wl:
                questions.append(f"{sc['id']}: which end of the stair is the bottom? (no walk line found)")
            if rise and not (0.13 <= rise <= 0.21):
                questions.append(f"{sc['id']}: rise {rise:.3f} m is unusual - check the tread count ({steps_total}) or floor height")
            z = v['base']
            for fi, f in enumerate(g['flights']):
                lines = f['lines']
                steps = []
                for i in range(len(lines)):              # step i: from riser line i to the next line (or one going on)
                    a0, a1 = lines[i]
                    if i + 1 < len(lines):
                        b0, b1 = lines[i + 1]
                    else:
                        dn = ((lines[i][0][0] - lines[i - 1][0][0]), (lines[i][0][1] - lines[i - 1][0][1])) if i else (0, 0)
                        b0 = (a0[0] + dn[0], a0[1] + dn[1]); b1 = (a1[0] + dn[0], a1[1] + dn[1])
                    z_top = z + (i + 1) * rise
                    steps.append({'outline': [list(map(lambda c: round(c, 4), p)) for p in (a0, a1, b1, b0, a0)],
                                  'base': round(v['base'], 4), 'top': round(z_top, 4)})
                z += len(lines) * rise
                sc['flights'].append({'risers': len(lines), 'width': round(f['width'], 3), 'going': round(f['going'], 3),
                                      'top_level': round(z, 4), 'steps': steps})
            # landings: beyond the last riser of a flight up to where the walk line turns, mirrored (the walk line runs
            # through the middle of the landing); spans both flights
            sc['landings'] = []
            for (g1, f1), (g2, f2) in zip(list(zip(g['flights'], sc['flights'])), list(zip(g['flights'], sc['flights']))[1:]):
                l1, l2 = g1['lines'][-1], g2['lines'][0]
                up1 = (l1[0][0] - g1['lines'][-2][0][0], l1[0][1] - g1['lines'][-2][0][1]) if len(g1['lines']) > 1 else (0, 0)
                nu = math.hypot(*up1) or 1
                up1 = (up1[0] / nu, up1[1] / nu)
                mid1 = Point((l1[0][0] + l1[1][0]) / 2, (l1[0][1] + l1[1][1]) / 2)
                if wl is not None:
                    seg = [wl.interpolate(t) for t in (g1['t'], g2['t'])]
                    part = LineString([wl.interpolate(g1['t'] + (g2['t'] - g1['t']) * s / 20) for s in range(21)]) if g2['t'] > g1['t'] else None
                    # farthest point of the walk line between the flights, measured along up1 from the last riser
                    far = max((((p[0] - mid1.x) * up1[0] + (p[1] - mid1.y) * up1[1]) for p in part.coords), default=0) if part else 0
                    depth = max(0.6, min(2 * far, 1.1 * max(g1['width'], g2['width'])))   # ~ a flight width
                else:
                    depth = g1['width']
                shift = lambda l, d: [(l[0][0] + up1[0] * d, l[0][1] + up1[1] * d), (l[1][0] + up1[0] * d, l[1][1] + up1[1] * d)]
                pts = list(l1) + shift(l1, depth) + list(l2) + shift(l2, depth)
                land = MultiPoint(pts).convex_hull
                if land.area > 0.2:
                    sc['landings'].append({'outline': [[round(x, 4), round(y, 4)] for x, y in land.exterior.coords],
                                           'base': round(v['base'], 4), 'top': f1['top_level'], 'depth': round(depth, 3)})
            out.append(sc)
        if a.plot and vid in a.plot.split(','):
            plot(a.project, vid, es, k, [s for s in out if s['view'] == vid])
    for s_ in skipped:
        print('SKIPPED', s_)
    json.dump({'project': a.project, 'staircases': out, 'questions': questions, 'skipped': skipped, 'notes_found': len(notes)},
              open(os.path.join(pdir, 'stairs.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for s in out:
        fl = ', '.join(f"{f['risers']} risers w {f['width']} g {f['going']}" for f in s['flights'])
        print(f"{s['id']:9} base {s['base']:+.2f} H {s['floor_to_floor']:.2f} | {s['risers']} risers × {s['rise']} m | flights: {fl} | "
              f"landings {len(s['landings'])} | {s['walk_line']}" + (f" | {s['note_check']}" if s.get('note_check') else ''))
    for q in questions:
        print('QUESTION:', q)


def plot(project, vid, es, k, scs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon as MP
    fig, ax = plt.subplots(figsize=(12, 8), dpi=110)
    for e in es:
        for path in e['paths']:
            ax.plot([p[0] * k for p in path], [p[1] * k for p in path], lw=0.5, color='#999')
    cmap = plt.get_cmap('viridis')
    for s in scs:
        for f in s['flights']:
            for st in f['steps']:
                ax.add_patch(MP([p[:2] for p in st['outline']], closed=True, fc=cmap((st['top'] - s['base']) / s['floor_to_floor']),
                                ec='black', lw=0.3, alpha=0.8))
        for l in s['landings']:
            ax.add_patch(MP(l['outline'], closed=True, fc='orange', ec='black', lw=0.5, alpha=0.5))
    ax.autoscale(); ax.set_aspect('equal'); ax.set_title(f'{vid} stairs: colour = step height (dark low -> yellow high), orange = landing')
    out = os.path.join(ROOT, 'views', project); os.makedirs(out, exist_ok=True)
    fn = os.path.join(out, f'stairs_built_{vid}.png'); fig.savefig(fn, bbox_inches='tight'); print('plot:', fn)


if __name__ == '__main__':
    main()
