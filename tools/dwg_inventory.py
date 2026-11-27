"""Summarise a full DWG dump (from tools/acad/dwg_inventory.lsp) for ANY drawing. Stdlib only, read-only.

Usage: python tools/dwg_inventory.py data/dwg_inventory.tsv [out_dir=data/inventory]
Writes:
  layers.csv   layer, entity counts (model/layouts vs inside block definitions), entity types
  blocks.csv   block name, entities in its definition, inserts in model space, layers used inside
  texts.csv    every TEXT/MTEXT/ATTRIB in model space and blocks (owner, layer, tag, point, height, clean text)
  dims.csv     every DIMENSION (owner, layer, point, measured value)
This is the first look at an unknown drawing: which layers hold walls, doors, windows, levels, room names.
"""
import collections
import csv
import os
import re
import sys
import sys as _sys
_sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # Windows console is cp1252: Cyrillic layer names

BS = chr(92)


UNITS = {0: 'unitless', 1: 'in', 2: 'ft', 4: 'mm', 5: 'cm', 6: 'm'}
UNIT_TO_M = {'mm': 0.001, 'cm': 0.01, 'm': 1.0, 'in': 0.0254, 'ft': 0.3048}


def load_meta(path):
    """Header lines written by dwg_inventory.lsp: #DWG, #PATH, #UNITS, #EXTMIN, #EXTMAX."""
    meta = {}
    for line in open(path, encoding='utf-8-sig'):
        if not line.startswith('#'):
            break
        k, _, v = line.rstrip('\n').partition('\t')
        meta[k[1:].lower()] = v
    if 'units' in meta:
        meta['units'] = UNITS.get(int(meta['units']), f"code {meta['units']}")
    return meta


def load(path):
    rows = []
    for line in open(path, encoding='utf-8-sig'):
        line = line.rstrip('\n')
        if line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) < 4 and rows:          # MTEXT with a hard newline: continuation of the previous row
            rows[-1][-1] += ' / ' + line
            continue
        rows.append(parts)
    return rows


def clean(t):
    """Strip MTEXT formatting codes (\\P new paragraph, \\f font, {...})."""
    t = re.sub(re.escape(BS) + r'[A-Za-z][^;' + re.escape(BS) + r']*;', '', t)
    return t.replace(BS + 'P', ' / ').replace('{', '').replace('}', '').strip()


def write_csv(path, header, rows):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def summarise(rows, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    p = lambda n: os.path.join(out_dir, n)
    in_model = lambda r: r[0].startswith('*')          # *Model, *<layout>, and *SUB (attributes of placed blocks)

    tot = collections.Counter(); direct = collections.Counter(); types = collections.defaultdict(collections.Counter)
    for r in rows:
        tot[r[2]] += 1
        types[r[2]][r[1]] += 1
        if in_model(r):
            direct[r[2]] += 1
    write_csv(p('layers.csv'), ['layer', 'entities_total', 'in_model_or_layouts', 'in_block_definitions', 'types'],
              [[lay, n, direct[lay], n - direct[lay], '; '.join(f'{k} {v}' for k, v in types[lay].most_common())]
               for lay, n in tot.most_common()])

    size = collections.Counter(r[0] for r in rows if not r[0].startswith('*'))
    inserts = collections.Counter(r[4] for r in rows if r[0] == '*Model' and r[1] == 'INSERT' and len(r) > 4)
    blk_layers = collections.defaultdict(collections.Counter)
    for r in rows:
        if not r[0].startswith('*'):
            blk_layers[r[0]][r[2]] += 1
    names = sorted(set(size) | set(inserts), key=lambda b: (-inserts[b], -size[b]))
    write_csv(p('blocks.csv'), ['block', 'entities_in_definition', 'inserts_in_model', 'layers_inside'],
              [[b, size[b], inserts[b], '; '.join(f'{k} {v}' for k, v in blk_layers[b].most_common(6))] for b in names])

    texts = [[r[0], r[1], r[2], r[4], r[5], r[6], clean(r[7])] for r in rows
             if r[1] in ('TEXT', 'MTEXT', 'ATTRIB') and len(r) > 7 and clean(r[7])]
    write_csv(p('texts.csv'), ['owner', 'type', 'layer', 'tag', 'point', 'height', 'text'], texts)

    dims = [[r[0], r[2], r[5], r[6]] for r in rows if r[1] == 'DIMENSION' and len(r) > 6]
    write_csv(p('dims.csv'), ['owner', 'layer', 'point', 'measurement'], dims)

    return {'rows': len(rows), 'layers': len(tot), 'blocks': len(names), 'texts': len(texts), 'dims': len(dims)}


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(sys.argv[1]) or '.', 'inventory')
    stats = summarise(load(sys.argv[1]), out)
    print(', '.join(f'{k} {v}' for k, v in stats.items()), '->', out)
