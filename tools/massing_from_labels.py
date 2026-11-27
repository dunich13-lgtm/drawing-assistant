"""Massing model data from a 2D drawing: closed shapes + height labels -> extrusions. Stdlib only.

Input: a layer dump from tools/acad/acad_layer_dump.ps1 (rows P = polyline, C = circle, T = text).
Rule:  a text like "H=56m" / "h = 12.5 m" / "H=560cm" gives the height of the closed shape it lies in.
       If the text lies in several shapes, the smallest one wins. Open polylines are ignored.
Usage: python tools/massing_from_labels.py data/massing_src.tsv data/massing.json --units cm [--circle-segments 48]
       --units = drawing units (mm, cm, m; from INSUNITS, see tools/acad/acad_list_docs.ps1)
Output JSON (metres): elements [{id, kind, outline, height, label, label_at, source}], plus every shape
without a label and every label without a shape, so nothing is silently dropped.
"""
import argparse
import json
import math
import re
import sys as _sys
_sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # Windows console is cp1252: Cyrillic layer names

UNIT = {'mm': 0.001, 'cm': 0.01, 'm': 1.0}
LABEL = re.compile(r'^\s*[Hh]\s*=\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|m)?\s*$')


def xy(s):
    a = s.split(',')
    return float(a[0]), float(a[1])


def area(pts):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


def inside(pt, pts):
    x, y = pt
    c = False
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def read(path, k, segs):
    shapes, labels = [], []
    for n, line in enumerate(open(path, encoding='utf-8-sig'), 1):
        f = line.rstrip('\n').split('\t')
        if f[0] == 'P' and f[2].endswith(' C'):
            pts = [xy(t) for t in f[2][:-2].split()]
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts.pop()
            if len(pts) >= 3:
                shapes.append({'kind': 'polyline', 'layer': f[1], 'line': n, 'pts': [(x * k, y * k) for x, y in pts]})
        elif f[0] == 'C':
            (cx, cy), r = xy(f[2]), float(f[3])
            pts = [((cx + r * math.cos(2 * math.pi * i / segs)) * k, (cy + r * math.sin(2 * math.pi * i / segs)) * k)
                   for i in range(segs)]
            shapes.append({'kind': 'circle', 'layer': f[1], 'line': n, 'pts': pts, 'center': [cx * k, cy * k], 'r': r * k})
        elif f[0] == 'T':
            m = LABEL.match(f[3])
            if m:
                h = float(m.group(1).replace(',', '.')) * UNIT[m.group(2) or 'm']
                x, y = xy(f[2])
                labels.append({'text': f[3].strip(), 'height': h, 'at': (x * k, y * k), 'layer': f[1], 'line': n})
    return shapes, labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--units', required=True, choices=UNIT)
    ap.add_argument('--circle-segments', type=int, default=48)
    a = ap.parse_args()
    shapes, labels = read(a.src, UNIT[a.units], a.circle_segments)

    used = set()
    elements, orphan_labels, conflicts = [], [], []
    for lb in labels:
        hits = [i for i, s in enumerate(shapes) if inside(lb['at'], s['pts'])]
        if not hits:
            orphan_labels.append(lb)
            continue
        i = min(hits, key=lambda j: area(shapes[j]['pts']))
        if i in used:
            conflicts.append(f"shape {i} has more than one label (also '{lb['text']}' at line {lb['line']})")
            continue
        used.add(i)
        s = shapes[i]
        elements.append({
            'id': f'M{len(elements) + 1}', 'kind': s['kind'], 'height': round(lb['height'], 4),
            'outline': [[round(x, 4), round(y, 4)] for x, y in s['pts']],
            'footprint_m2': round(area(s['pts']), 2), 'label': lb['text'],
            'label_at': [round(v, 4) for v in lb['at']],
            'source': f"{s['kind']} on layer '{s['layer']}' (dump line {s['line']}) + text '{lb['text']}' (line {lb['line']})",
            **({'center': [round(v, 4) for v in s['center']], 'radius': round(s['r'], 4)} if s['kind'] == 'circle' else {}),
        })
    unlabelled = [{'kind': s['kind'], 'layer': s['layer'], 'line': s['line'], 'footprint_m2': round(area(s['pts']), 2)}
                  for i, s in enumerate(shapes) if i not in used]
    out = {'source_dump': a.src, 'units_in': a.units, 'elements': elements, 'unlabelled_shapes': unlabelled,
           'labels_without_shape': [{'text': l['text'], 'at': l['at'], 'line': l['line']} for l in orphan_labels],
           'conflicts': conflicts}
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for e in elements:
        print(f"{e['id']} {e['kind']:8} H={e['height']} m  footprint {e['footprint_m2']} m2  <- {e['source']}")
    print(f"unlabelled shapes {len(unlabelled)}, labels without shape {len(orphan_labels)}, conflicts {len(conflicts)}")


if __name__ == '__main__':
    main()
