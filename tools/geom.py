"""Parse geometry dumps from AutoCAD into Python shapes (stdlib only).

load(path)        -> entities from tools/acad/dwg_block_geom.lsp output (one block definition)
hatch_loops(...)  -> closed boundary loops of a HATCH (polyline and edge loops, arcs and bulges flattened)
bulge_pts(p,q,b)  -> points of a polyline segment with bulge
in_box(e, box)    -> True if any point of the entity lies in (x0, y0, x1, y1)

Every entity is a dict: type, layer, handle, paths (list of point lists, drawing units) plus type-specific keys
(closed, center/r, name/pt/rot/scale for INSERT, pt/h/text for TEXT, pattern for HATCH).
"""
import math


def _pt(s):
    a = s.split(',')
    return float(a[0]), float(a[1])


def _arc_pts(cx, cy, r, a0, a1, seg_deg=10):
    while a1 < a0:
        a1 += 2 * math.pi
    n = max(2, int(math.degrees(a1 - a0) / seg_deg) + 1)
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def bulge_pts(p, q, b):
    """Points of a polyline segment p->q with bulge b (excluding q)."""
    if abs(b) < 1e-9:
        return [p]
    th = 4 * math.atan(b)                       # included angle, signed (+ = counter-clockwise)
    dx, dy = q[0] - p[0], q[1] - p[1]
    c = math.hypot(dx, dy)
    if c < 1e-12:
        return [p]
    r = c / (2 * math.sin(th / 2))
    mx, my = (p[0] + q[0]) / 2, (p[1] + q[1]) / 2
    h = r * math.cos(th / 2)
    cx, cy = mx - dy / c * h, my + dx / c * h
    a0 = math.atan2(p[1] - cy, p[0] - cx)
    rr = math.hypot(p[0] - cx, p[1] - cy)
    n = max(2, int(abs(math.degrees(th)) / 10))
    return [(cx + rr * math.cos(a0 + th * i / n), cy + rr * math.sin(a0 + th * i / n)) for i in range(n)]


def load(path):
    ents = []
    for line in open(path, encoding='utf-8-sig'):
        line = line.rstrip('\n')
        if not line or line.startswith('#'):
            continue
        f = line.split('\t')
        if len(f) < 3:
            continue
        typ, layer, handle, d = f[0], f[1], f[2], f[3:]
        e = {'type': typ, 'layer': layer, 'handle': handle, 'paths': []}
        try:
            if typ == 'LINE':
                e['paths'] = [[_pt(d[0]), _pt(d[1])]]
            elif typ == 'LWPOLYLINE':
                closed = d[0] == '1'
                vs = []
                for tok in d[1:]:
                    a = tok.split(',')
                    vs.append((float(a[0]), float(a[1]), float(a[2]) if len(a) > 2 else 0.0))
                pts = []
                n = len(vs)
                for i in range(n if closed else n - 1):
                    p, q = vs[i], vs[(i + 1) % n]
                    pts += bulge_pts(p[:2], q[:2], p[2])
                if not closed and vs:
                    pts.append(vs[-1][:2])
                elif pts:
                    pts.append(pts[0])
                e['closed'] = closed
                e['paths'] = [pts]
            elif typ == 'ARC':
                cx, cy = _pt(d[0]); r = float(d[1])
                e['paths'] = [_arc_pts(cx, cy, r, float(d[2]), float(d[3]))]
            elif typ == 'CIRCLE':
                cx, cy = _pt(d[0]); r = float(d[1])
                e['paths'] = [_arc_pts(cx, cy, r, 0, 2 * math.pi)]
                e['center'], e['r'] = (cx, cy), r
            elif typ == 'INSERT':
                e['name'] = d[0]; e['pt'] = _pt(d[1]); e['rot'] = float(d[2])
                e['scale'] = tuple(float(x) for x in d[3].split(','))
            elif typ in ('TEXT', 'MTEXT'):
                e['pt'] = _pt(d[0]); e['h'] = float(d[1]); e['text'] = '\t'.join(d[2:])
            elif typ == 'HATCH':
                e['pattern'] = d[0]
                e['paths'] = hatch_loops(d[1:])
        except (ValueError, IndexError):
            e['paths'] = []
            e['parse_error'] = True
        ents.append(e)
    return ents


def hatch_loops(toks):
    """Boundary loops of a hatch from raw 'code=value' tokens (DXF group codes)."""
    g = []
    for t in toks:
        if '=' in t:
            c, v = t.split('=', 1)
            g.append((int(c), v))
    loops = []
    i = 0
    while i < len(g):
        c, v = g[i]
        if c != 92:
            i += 1
            continue
        flag = int(v)
        i += 1
        pts = []
        if flag & 2:            # polyline loop: 72 has-bulge, 73 closed, 93 count, then 10 (+42 bulge)
            verts = []
            while i < len(g) and g[i][0] != 92:
                c, v = g[i]
                if c == 10:
                    verts.append([*_pt(v), 0.0])
                elif c == 42 and verts:
                    verts[-1][2] = float(v)
                i += 1
            for k in range(len(verts)):
                p, q = verts[k], verts[(k + 1) % len(verts)]
                pts += bulge_pts(p[:2], q[:2], p[2])
        else:                   # edge loop: 93 count, then per edge 72 type + data
            while i < len(g) and g[i][0] != 92:
                c, v = g[i]
                if c == 72:
                    et = int(v)
                    i += 1
                    if et == 1 and i + 1 < len(g):          # line: 10 start, 11 end
                        a = _pt(g[i][1]); b = _pt(g[i + 1][1]); i += 2
                        if not pts or math.dist(pts[-1], a) > 1e-6:
                            pts.append(a)
                        pts.append(b)
                    elif et == 2 and i + 3 < len(g):        # arc: 10 centre, 40 r, 50 a0, 51 a1, 73 ccw
                        cx, cy = _pt(g[i][1]); r = float(g[i + 1][1])
                        a0 = math.radians(float(g[i + 2][1])); a1 = math.radians(float(g[i + 3][1]))
                        ccw = 1
                        i += 4
                        if i < len(g) and g[i][0] == 73:
                            ccw = int(g[i][1]); i += 1
                        if ccw:
                            pts += _arc_pts(cx, cy, r, a0, a1)
                        else:                                # clockwise: angles are measured the other way
                            pts += [(cx + r * math.cos(-a), cy + r * math.sin(-a)) for a in
                                    [a0 + (a1 - a0) * t / 8 for t in range(9)]]
                else:
                    i += 1
        if len(pts) >= 3:
            if math.dist(pts[0], pts[-1]) > 1e-6:
                pts.append(pts[0])
            loops.append(pts)
    return loops


def in_box(e, box):
    x0, y0, x1, y1 = box
    for path in e['paths']:
        for x, y in path:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return True
    if 'pt' in e:
        x, y = e['pt']
        return x0 <= x <= x1 and y0 <= y <= y1
    return False


def polygon_area(pts):
    """Signed area (shoelace); positive = counter-clockwise."""
    a = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        a += x1 * y2 - x2 * y1
    return a / 2
