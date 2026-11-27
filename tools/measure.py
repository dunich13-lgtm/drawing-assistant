"""Measure building values in the drawing itself, so they don't have to be asked (user, 2026-11-27:
"it is pointless to be called automatic if I have to answer so many questions").

  slab thickness   cut slabs in SECTION views: horizontal areas at least half as wide as the section and 8-50 cm
                   thick; the thickness that occurs most often (>= 2 cuts) wins.
  window sill/head facade/section opening rectangles (tools/sections.py) that sit on a floor level: a group of
  door head        >= 3 identical ones (sill/head within 2 cm) is taken as the typical opening of that kind.
Values found here are used AUTOMATICALLY (with their source) by openings.py and build_data.py; a value the user
set explicitly still wins. Nothing is guessed: if nothing is measurable, the value stays empty and is asked.
Usage: python tools/measure.py <project>  -> data/<project>/measured.json
"""
import collections
import json
import os
import statistics
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slab_thickness(areas, views):
    sec = {v['id']: v for v in views if v['kind'] == 'section'}
    cuts = []
    for a in areas:
        v = sec.get(a['view'])
        if not v:
            continue
        xs = [p[0] for p in a['shape'][0]['outline']]
        ys = [p[1] for p in a['shape'][0]['outline']]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        vw = v['bbox_m'][2] - v['bbox_m'][0]
        if w >= max(2.0, 0.5 * vw) and 0.08 <= h <= 0.5:
            cuts.append((round(h, 2), a['id'], v['titles'][0]['text'] if v['titles'] else v['id'], round(w, 2)))
    if not cuts:
        return None
    count = collections.Counter(c[0] for c in cuts)
    t, n = count.most_common(1)[0]
    if n < 2:
        return None
    where = sorted({c[2] for c in cuts if c[0] == t})
    return {'value': t, 'source': f"measured: {n} cut slabs {t:.2f} m thick in {'; '.join(w[:40] for w in where)}",
            'all_cuts': [{'thickness': c[0], 'area': c[1], 'width_m': c[3]} for c in cuts]}


def typical_openings(sections):
    groups = collections.defaultdict(list)
    for s in sections:
        levels = sorted(s.get('levels', []))
        for o in s.get('opening_candidates', []):
            if o['sill_above_floor'] is None or o['head_above_floor'] is None:
                continue
            above = [l for l in levels if l > o['floor'] + 0.01]
            if not above or o['head_above_floor'] > (above[0] - o['floor']) - 0.05:
                continue      # on the top level (chimneys, roof parts) or taller than the storey: not an opening
            key = ('door' if o['sill_above_floor'] < 0.10 else 'window',
                   round(o['sill_above_floor'] / 0.02) * 0.02, round(o['head_above_floor'] / 0.02) * 0.02)
            groups[key].append((s['title'], o))
    out = {}
    for (kind, _, _), items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if kind in out or len(items) < 3:
            continue
        sills = [o['sill_above_floor'] for _, o in items]
        heads = [o['head_above_floor'] for _, o in items]
        where = collections.Counter(t for t, _ in items).most_common(1)[0][0]
        out[kind] = {'sill': round(statistics.median(sills), 3), 'head': round(statistics.median(heads), 3), 'n': len(items),
                     'source': f"measured: {len(items)} identical {kind}s on '{where[:40]}' (sill {statistics.median(sills):.2f}, "
                               f"head {statistics.median(heads):.2f} above floor)"}
    return out


def main(project):
    pdir = os.path.join(ROOT, 'data', project)
    ar = json.load(open(os.path.join(pdir, 'areas.json'), encoding='utf-8'))
    spath = os.path.join(pdir, 'sections.json')
    secs = json.load(open(spath, encoding='utf-8'))['views'] if os.path.exists(spath) else []
    m = {'slab_thickness': slab_thickness(ar['areas'], ar['views']), 'openings': typical_openings(secs)}
    json.dump(m, open(os.path.join(pdir, 'measured.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    s = m['slab_thickness']
    print('slab thickness:', f"{s['value']} m - {s['source']}" if s else 'not measurable (will be asked)')
    for k in ('window', 'door'):
        o = m['openings'].get(k)
        print(f'{k}:', f"sill {o['sill']} / head {o['head']} - {o['source']}" if o else 'not measurable (will be asked)')


if __name__ == '__main__':
    main(sys.argv[1])
