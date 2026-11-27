"""Project setup proposal (spec 002 R1 / NIN-6). Stdlib only, read-only.

Reads the inventory dumps of a project (tools/acad/acad_inventory_all.ps1 -> data/<project>/inventory/*.tsv)
and PROPOSES:
  data/<project>/layermap.json   role of every layer (object / opening / annotation / level_marks / ignore / unknown)
                                 with the reason, entity counts and confidence
  data/<project>/project.json    units, scale to metres, ±0.00, gap tolerance, profile suggestion, drawings
  data/<project>/setup_summary.md  plain-language summary + the questions for the user
Both JSON files start with "confirmed": false. Nothing is used for building until the user confirms.
Existing confirmed files are never overwritten by a new proposal.

Usage:
  python tools/project_setup.py <project>                                   propose (after the inventory)
  python tools/project_setup.py <project> --layer "0=object" --profile generic --zero 0 --gap-mm 5   apply answers
  python tools/project_setup.py <project> --confirm                         user confirmed: lock it in
"""
import collections
import glob
import json
import os
import re
import sys
import sys as _sys
_sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # Windows console is cp1252: Cyrillic layer names

sys.path.insert(0, os.path.dirname(__file__))
import dwg_inventory as inv  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Layer-name keywords (English, Bulgarian, German, common CAD standards). Order matters: first match wins.
RULES = [
    ('ignore', 'viewport / frame / title block / table', r'defpoints|vport|viewport|frame|border|рамк|щамп|антетк|таблиц|title|titel|plankopf|\bsheet\b|лист'),
    ('ignore', 'dimensions', r'dim|bem|размер|оразмер|maß'),
    ('ignore', 'axes / grid', r'axis|axes|grid|\bоси?\b|raster|achse'),
    ('ignore', 'furniture / fixtures / landscape', r'furn|обзав|mobel|möbel|equip|оборуд|уреди|техник|санитар|осветл|lighting|растит|зелен|vegetat|улуц|gutter|кран|kran'),
    ('ignore', 'demolition', r'демонт|demol|abbruch'),
    ('ignore', 'construction details', r'^td\d|детайл|detail|fasten|gasket|flashing'),
    ('ignore', 'insulation / plaster / finish layers', r'изолац|insul|dämm|\beps\b|_eps|eps_|\bxps\b|_xps|xps_|мин\.?\s*ват|min_?vata|baumit|мазил|mazil|замаз|toplo|poliuretan|plaster|putz'),
    ('section_cut', 'section cut lines', r'линия\s*разрез|section.?line|cut.?line|schnittlinie'),
    ('level_marks', 'level marks / floor levels', r'level|кот[аи]|котир|kote|höhe|elev\b|ниво'),
    ('annotation', 'text / annotation', r'text|txt|[tт][xх][tт]|текст|надпис|anno|beschr|label|room.?name|помещ|специф'),
    ('section_view', 'section / elevation linework', r'изглед|разрез|izgled|\braz\b|section|elevation|ansicht|schnitt|wl-sec|wl-vis|view'),
    ('opening', 'doors', r'door|врат|tür|tuer'),
    ('opening', 'windows', r'window|win\b|прозор|fenster|дограм|dograma|glaz'),
    ('object', 'walls / structure', r'wall|стен|wand|зид|beton|бетон|стоманобет|concrete|\brc\b|column|колон|stütz|slab|плоч|plocha|decke|struct|констр|tuhla|тухла'),
    ('object', 'stairs / roof', r'стълб|stair|treppe|покрив|roof|dach'),
    ('object', 'objects / installation', r'object|обект|skulpt|скулпт|install|инстал|massing|volume|обем|building|сград'),
    # Last on purpose: a wall hatch ("A-WALL-HATCH") must stay an object; only other hatches are finishes/patterns.
    ('ignore', 'hatch for finishes / patterns', r'hatch|щрих|штрих|schraff|pattern|насти'),
]
GEOM = {'LINE', 'LWPOLYLINE', 'POLYLINE', 'ARC', 'CIRCLE', 'ELLIPSE', 'SPLINE', 'HATCH'}
TEXT = {'TEXT', 'MTEXT', 'ATTRIB', 'ATTDEF'}
# AutoCAD writes ± as the control code %%p (also %%P); level texts may carry a unit or a label after the number.
PM = r'(?:±|%%[pP]|\+/-|\+-)'
LEVEL_TEXT = re.compile(r'^\s*(' + PM + r'|[+\-])?\s*\d{1,3}[.,]\d{2,3}\s*(m|м)?\s*$')
ZERO_TEXT = re.compile(PM + r'\s*0[.,]00|^\s*[+\-]?\s*0[.,]000?\s*(m|м)?\s*$')
HEIGHT_LABEL = re.compile(r'^\s*[Hh]\s*=\s*\d')
VIEW_TITLE = re.compile(r'разрез|сечение|фасада|section|elevation|schnitt|ansicht', re.I)
TITLE_BLOCK = re.compile(r'title|щамп|рамк|frame|border|plankopf|^a[0-4]\b', re.I)


def classify(layer, types):
    name = layer.lower()
    kinds = set(types)
    # What is actually on the layer beats its name ("183-ТХТ дограма" holds only texts: annotation, not windows).
    if kinds and kinds <= {'DIMENSION'}:
        return 'ignore', 'only dimensions on this layer', 'high'
    if kinds and kinds <= TEXT:
        return 'annotation', 'only texts on this layer', 'high'
    if kinds and kinds <= {'POINT'}:
        return 'ignore', 'only points on this layer', 'high'
    for role, why, pat in RULES:
        if re.search(pat, name):
            return role, f"name matches '{why}'", 'medium'
    if kinds and kinds <= {'INSERT'}:
        return 'unknown', 'only block inserts (could be doors/windows, furniture, symbols)', 'low'
    if kinds & GEOM:
        return 'unknown', 'geometry with no recognisable layer name', 'low'
    return 'ignore', 'no geometry', 'medium'


def propose(project):
    pdir = os.path.join(ROOT, 'data', project)
    dumps = sorted(glob.glob(os.path.join(pdir, 'inventory', '*.tsv')))
    if not dumps:
        sys.exit(f'No dumps in {pdir}\\inventory. Run tools\\acad\\acad_inventory_all.ps1 -Project {project} first.')

    drawings, layers = [], collections.defaultdict(lambda: {'types': collections.Counter(), 'drawings': set(),
                                                             'in_model': 0, 'in_blocks': 0})
    levels, zeros, height_labels, views, title_blocks = [], [], [], [], set()
    units_seen = set()
    for path in dumps:
        meta = inv.load_meta(path)
        rows = inv.load(path)
        dname = meta.get('dwg', os.path.basename(path))
        units_seen.add(meta.get('units', '?'))
        drawings.append({'drawing': dname, 'folder': meta.get('path', ''), 'units': meta.get('units', '?'),
                         'extents': [meta.get('extmin'), meta.get('extmax')], 'entities': len(rows),
                         'dump': os.path.relpath(path, ROOT)})
        for r in rows:
            if len(r) < 4:
                continue
            L = layers[r[2]]
            L['types'][r[1]] += 1
            L['drawings'].add(dname)
            L['in_model' if r[0].startswith('*') else 'in_blocks'] += 1
            if r[1] == 'INSERT' and len(r) > 4 and TITLE_BLOCK.search(r[4]):
                title_blocks.add(r[4])
            if r[1] in TEXT and len(r) > 7:
                t = inv.clean(r[7])
                src = {'text': t, 'layer': r[2], 'at': r[5], 'drawing': dname, 'owner': r[0]}
                if ZERO_TEXT.search(t):
                    zeros.append(src)
                elif LEVEL_TEXT.match(t):
                    levels.append(src)
                if HEIGHT_LABEL.match(t):
                    height_labels.append(src)
                if VIEW_TITLE.search(t):
                    views.append(src)

    lm = {}
    for name, L in sorted(layers.items(), key=lambda kv: -sum(kv[1]['types'].values())):
        role, why, conf = classify(name, L['types'])
        lm[name] = {'role': role, 'reason': why, 'confidence': conf, 'height_rule': None,
                    'entities': dict(L['types'].most_common()), 'in_model': L['in_model'],
                    'in_blocks': L['in_blocks'], 'drawings': sorted(L['drawings'])}

    units = units_seen.pop() if len(units_seen) == 1 else None
    scale = inv.UNIT_TO_M.get(units) if units else None
    has_building = any(v['role'] in ('opening',) or 'wall' in v['reason'] for v in lm.values())
    project_json = {
        'project': project, 'confirmed': False,
        'drawings': drawings,
        'units': units, 'units_to_m': scale,
        'zero_level': ({'value': 0.0, 'source': f"'{zeros[0]['text']}' on layer {zeros[0]['layer']} in {zeros[0]['drawing']}"}
                       if zeros else None),
        'gap_tolerance_mm': 5, 'gap_tolerance_drawing_units': (0.005 / scale) if scale else None,
        'profile': None, 'profile_suggestion': 'building' if has_building else 'generic',
        'found': {'level_marks': len(levels), 'zero_marks': len(zeros), 'height_labels': len(height_labels),
                  'section_or_elevation_titles': [v['text'] for v in views][:20],
                  'title_blocks': sorted(title_blocks)},
    }
    layermap = {'project': project, 'confirmed': False, 'layers': lm,
                'roles': {'object': 'closed areas on these layers become 3D objects',
                          'opening': 'door/window blocks or geometry (building profile)',
                          'annotation': 'texts used as labels (H=...), room names - not built',
                          'level_marks': 'level marks used for heights - not built',
                          'section_cut': 'section cut lines (A-A) linking plans to sections - not built',
                          'section_view': 'linework of sections / elevations, read for heights - not built',
                          'ignore': 'never built', 'unknown': 'ASK THE USER before building'}}

    questions = []
    if not units:
        questions.append(f'Drawing units are unclear ({", ".join(sorted(map(str, units_seen)))}). Which unit is used?')
    unknown = [n for n, v in lm.items() if v['role'] == 'unknown']
    if unknown:
        questions.append('What is on these layers (object / opening / ignore)? ' + ', '.join(unknown[:30]))
    questions.append(f"Profile: building or generic (installation / objects)? Suggestion: {project_json['profile_suggestion']}.")
    if not zeros:
        questions.append('No ±0.00 mark found. Where is ±0.00 (or is the drawing\'s z = 0 the project zero)?')
    if len(drawings) > 1:
        questions.append('Do all these drawings belong to the project? ' + ', '.join(d['drawing'] for d in drawings))
    questions.append('Gap tolerance 5 mm (lines closer than this are joined): OK?')

    write = lambda n, obj: _write_unless_confirmed(os.path.join(pdir, n), obj)
    write('layermap.json', layermap)
    write('project.json', project_json)

    by_role = collections.defaultdict(list)
    for n, v in lm.items():
        by_role[v['role']].append(f"`{n}` ({sum(v['entities'].values())}: {', '.join(f'{k} {c}' for k, c in list(v['entities'].items())[:3])}) - {v['reason']}")
    md = [f'# Setup proposal: {project}', '',
          '## Drawings', *[f"- {d['drawing']} - {d['entities']} entities, units {d['units']}" for d in drawings], '',
          f"Units: **{units or '?'}** (x {scale} to metres) · ±0.00: **{'found' if zeros else 'not found'}** · "
          f"level marks: {len(levels)} · height labels (H=...): {len(height_labels)} · "
          f"section/elevation titles: {len(views)}", '',
          '## Layers by proposed role']
    for role in ('object', 'opening', 'annotation', 'level_marks', 'section_cut', 'section_view', 'unknown', 'ignore'):
        if by_role[role]:
            md += [f'### {role} ({len(by_role[role])})', *[f'- {s}' for s in by_role[role]], '']
    md += ['## Questions for you', *[f'{i}. {q}' for i, q in enumerate(questions, 1)]]
    with open(os.path.join(pdir, 'setup_summary.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md) + '\n')
    print('\n'.join(md))


def _write_unless_confirmed(path, obj):
    if os.path.exists(path):
        try:
            if json.load(open(path, encoding='utf-8')).get('confirmed'):
                print(f'(kept {os.path.basename(path)}: already confirmed by the user)')
                return
        except ValueError:
            pass
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def confirm(project):
    pdir = os.path.join(ROOT, 'data', project)
    for n in ('layermap.json', 'project.json'):
        p = os.path.join(pdir, n)
        d = json.load(open(p, encoding='utf-8'))
        if n == 'layermap.json':
            left = [k for k, v in d['layers'].items() if v['role'] == 'unknown']
            if left:
                sys.exit(f'Cannot confirm: layers still unknown: {", ".join(left)}')
        if n == 'project.json' and (not d.get('profile') or not d.get('units')):
            sys.exit('Cannot confirm: set "profile" and "units" in project.json first.')
        d['confirmed'] = True
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    print(f'{project}: layermap.json and project.json confirmed.')


def answer(project, layers=(), profile=None, zero=None, gap_mm=None, units=None):
    """Apply the user's answers to the proposal (before --confirm)."""
    pdir = os.path.join(ROOT, 'data', project)
    lp, pp = os.path.join(pdir, 'layermap.json'), os.path.join(pdir, 'project.json')
    lm, pj = json.load(open(lp, encoding='utf-8')), json.load(open(pp, encoding='utf-8'))
    roles = set(lm['roles'])
    for spec in layers:                       # "NAME=role" or "NAME=object:3.2" (layer height rule in metres)
        name, _, val = spec.partition('=')
        role, _, h = val.partition(':')
        if name not in lm['layers']:
            sys.exit(f'Unknown layer: {name}')
        if role not in roles:
            sys.exit(f'Unknown role {role}; use one of {", ".join(sorted(roles))}')
        L = lm['layers'][name]
        L.update(role=role, reason='set by the user', confidence='user')
        if h:
            L['height_rule'] = float(h)
    if units:
        pj['units'], pj['units_to_m'] = units, inv.UNIT_TO_M[units]
        pj['gap_tolerance_drawing_units'] = pj['gap_tolerance_mm'] / 1000 / pj['units_to_m']
    if profile:
        pj['profile'] = profile
    if zero is not None:                      # drawing z of the project ±0.00, as told by the user
        pj['zero_level'] = {'value': float(zero), 'source': 'set by the user'}
    if gap_mm is not None:
        pj['gap_tolerance_mm'] = float(gap_mm)
        if pj.get('units_to_m'):
            pj['gap_tolerance_drawing_units'] = float(gap_mm) / 1000 / pj['units_to_m']
    for p, d in ((lp, lm), (pp, pj)):
        d['confirmed'] = False                # any change needs a new confirmation
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    left = [k for k, v in lm['layers'].items() if v['role'] == 'unknown']
    print(f"answers saved. still unknown layers: {', '.join(left) or 'none'} | profile: {pj.get('profile')} | "
          f"zero: {pj.get('zero_level')} | gap: {pj['gap_tolerance_mm']} mm")


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Propose, answer and confirm the project setup (see module doc).')
    ap.add_argument('project')
    ap.add_argument('--confirm', action='store_true', help='mark layermap.json + project.json as confirmed by the user')
    ap.add_argument('--layer', action='append', default=[], help='NAME=role or NAME=object:<height m> (repeatable)')
    ap.add_argument('--profile', choices=['building', 'generic'])
    ap.add_argument('--zero', type=float, help='drawing z of the project ±0.00 (usually 0)')
    ap.add_argument('--gap-mm', type=float)
    ap.add_argument('--units', choices=sorted(inv.UNIT_TO_M))
    a = ap.parse_args()
    if a.confirm:
        confirm(a.project)
    elif a.layer or a.profile or a.zero is not None or a.gap_mm is not None or a.units:
        answer(a.project, a.layer, a.profile, a.zero, a.gap_mm, a.units)
    else:
        propose(a.project)
