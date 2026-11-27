"""Acceptance check 1 of spec 002 (NIN-7): every drawing style gives the right closed areas.
Drawing units: cm, gap tolerance 5 mm = 0.5 units, gaps reported up to 10x = 5 units.
Run: python tests/test_areas.py
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import geom   # noqa: E402
import areas  # noqa: E402

T = '\t'


def rect_lines(x, y, w, h, layer, gap=0.0):
    """4 loose LINEs; `gap` shortens the last line so the rectangle is not closed by that much."""
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    rows = []
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        if i == 3 and gap:
            b = (b[0], b[1] + gap)
        rows.append(f'LINE{T}{layer}{T}h{x}{i}{T}{a[0]},{a[1]}{T}{b[0]},{b[1]}')
    return rows


rows = []
rows += rect_lines(0, 0, 400, 300, 'LOOSE')                                     # A: 4 loose lines
rows += [f'LWPOLYLINE{T}OPEN{T}p1{T}0{T}600,0,0{T}1000,0,0{T}1000,300,0',        # B: two open polylines that meet
         f'LWPOLYLINE{T}OPEN{T}p2{T}0{T}1000,300,0{T}600,300,0{T}600,0,0']
rows += [f'HATCH{T}HATCHED{T}hh{T}SOLID{T}92=2{T}72=0{T}73=1{T}93=4{T}10=1200,0{T}10=1500,0{T}10=1500,300{T}10=1200,300']  # C
rows += [f'LWPOLYLINE{T}CLOSED{T}cp{T}1{T}1700,0,0{T}2000,0,0{T}2000,300,0{T}1700,300,0']   # D: closed polyline
rows += [f'CIRCLE{T}CIRC{T}cc{T}2300,150{T}150']                                 # E: circle
rows += rect_lines(2600, 0, 300, 300, 'GAP3', gap=0.3)                           # F: 3 mm gap -> joined
rows += rect_lines(3100, 0, 300, 300, 'GAP20', gap=2.0)                          # G: 20 mm gap -> reported, not closed
rows += [f'LWPOLYLINE{T}NEST{T}n1{T}1{T}0,600,0{T}800,600,0{T}800,1200,0{T}0,1200,0',    # H: outer
         f'LWPOLYLINE{T}NEST{T}n2{T}1{T}300,800,0{T}500,800,0{T}500,1000,0{T}300,1000,0']  # I: inside H
rows += [f'LWPOLYLINE{T}ARCS{T}ar{T}1{T}1000,600,1{T}1400,600,1']                # J: closed polyline of two half-circles (bulge 1) = circle r 200
rows += [f'LINE{T}LOOSE{T}dup{T}0,0{T}400,0']                                    # duplicate of A's bottom line

path = os.path.join(tempfile.mkdtemp(), 'geo.tsv')
open(path, 'w', encoding='utf-8').write('\n'.join(rows) + '\n#DONE\n')
found, rep = areas.find_areas(geom.load(path), tol=0.5, report_max=5.0, min_area=1.0)

def area_at(x, y):
    from shapely.geometry import Point
    hits = [a for a in found if a['geom'].contains(Point(x, y))]
    return min(hits, key=lambda a: a['geom'].area) if hits else None

checks = []
def check(name, ok, info=''):
    checks.append(ok)
    print(('PASS ' if ok else 'FAIL ') + name + (f'  ({info})' if info else ''))

a = area_at(200, 150);  check('A 4 loose lines -> one area 400x300', a is not None and abs(a['geom'].area - 120000) < 1, a and a['kind'])
b = area_at(800, 150);  check('B open polylines meeting -> area 400x300', b is not None and abs(b['geom'].area - 120000) < 1, b and b['kind'])
c = area_at(1350, 150); check('C hatch -> explicit area', c is not None and c['kind'] == 'explicit:hatch')
d = area_at(1850, 150); check('D closed polyline -> explicit area', d is not None and d['kind'] == 'explicit:lwpolyline')
e = area_at(2300, 150); check('E circle -> explicit area ~pi r2', e is not None and abs(e['geom'].area - 3.14159 * 150 ** 2) / (3.14159 * 150 ** 2) < 0.01, e and round(e['geom'].area))
f = area_at(2750, 150); check('F 3 mm gap -> joined, area found', f is not None and abs(f['geom'].area - 90000) < 50)
g = area_at(3250, 150); check('G 20 mm gap -> NOT closed', g is None)
big = [x for x in rep['gaps_too_big'] if 3090 < x['at'][0] < 3110]
check('G 20 mm gap -> reported as too big', len(big) >= 1 and abs(big[0]['gap'] - 2.0) < 0.01, big[:1])
check('3 mm gap counted once as joined', rep['gaps_joined'] == 1, rep['gaps_joined'])
i = area_at(400, 900); h = area_at(100, 700)
check('H/I nested: inner has the outer as parent', i is not None and h is not None and i['parent'] is not None
      and found[i['parent']] is h, f"inner {i and i['kind']}, outer {h and h['kind']}")
j = area_at(1200, 600); check('J polyline with arcs (bulges) -> circle r200', j is not None and abs(j['geom'].area - 3.14159 * 200 ** 2) / (3.14159 * 200 ** 2) < 0.02, j and round(j['geom'].area))
check('duplicate line reported as overlap', rep['overlapping_line_length'] >= 399, round(rep['overlapping_line_length']))
check('exactly 9 areas (A-F, H-J; G stays open)', len(found) == 9, f'{len(found)} areas: ' + ', '.join(sorted(a["kind"] for a in found)))
print(f'\n{sum(checks)}/{len(checks)} passed')
sys.exit(0 if all(checks) else 1)
