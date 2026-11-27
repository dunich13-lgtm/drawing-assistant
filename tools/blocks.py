"""Expand block inserts into world geometry (stdlib). Block definitions come from
tools/acad/acad_dump_block_defs.ps1 -> data/<project>/blocks/<name>.tsv (local block coordinates, geom.load format).

expand(ents, project, layers=None) -> ents with every INSERT replaced by the entities of its block, transformed by the
insert (scale incl. mirroring, rotation, position), recursively. Entities inside a block on layer "0" take the insert's
layer (AutoCAD rule). `layers`: keep only these layers after expansion (None = all). Missing block files are reported.
"""
import math
import os
import re

import geom

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def block_path(project, name):
    return os.path.join(ROOT, 'data', project, 'blocks', re.sub(r'[^\w\-]', '_', name) + '.tsv')


def _tf(insert):
    (px, py), rot, (sx, sy) = insert['pt'], insert['rot'], insert['scale'][:2]
    c, s = math.cos(rot), math.sin(rot)
    return lambda x, y: (px + c * x * sx - s * y * sy, py + s * x * sx + c * y * sy)


def expand(ents, project, layers=None, depth=0, missing=None):
    missing = set() if missing is None else missing
    out = []
    for e in ents:
        if e['type'] != 'INSERT':
            out.append(e)
            continue
        p = block_path(project, e['name'])
        if depth > 4 or not os.path.exists(p):
            missing.add(e['name'])
            continue
        f = _tf(e)
        sub = expand(geom.load(p), project, None, depth + 1, missing)
        for s in sub:
            t = dict(s)
            t['paths'] = [[f(x, y) for x, y in path] for path in s['paths']]
            if 'pt' in s:
                t['pt'] = f(*s['pt'])
            if 'center' in s:
                t['center'] = f(*s['center'])
            if s['layer'] == '0':
                t['layer'] = e['layer']
            t['from_block'] = e['name']
            out.append(t)
    if layers is not None and depth == 0:
        out = [e for e in out if e['layer'] in layers]
    if depth == 0:
        expand.missing = sorted(missing)
    return out
