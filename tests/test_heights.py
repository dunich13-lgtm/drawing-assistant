"""NIN-8: height/base priority, conflicts, proposals, answers, questions. Run: python tests/test_heights.py"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import heights as H  # noqa: E402


def sq(aid, view, x, layer='WALL', w=4.0):
    return {'id': aid, 'view': view, 'layers': [layer], 'shape': [{'outline': [[x, 0], [x + w, 0], [x + w, w], [x, w]], 'holes': []}]}


views = [{'id': 'V1', 'kind': 'plan', 'titles': [{'text': 'План етаж 1 / кота %%P0.00'}]},
         {'id': 'V2', 'kind': 'plan', 'titles': [{'text': 'План етаж 2 / кота +2.80'}]},
         {'id': 'V3', 'kind': 'section', 'titles': [{'text': 'РАЗРЕЗ А-А'}]},
         {'id': 'V4', 'kind': 'unknown', 'titles': []}]
# views sit side by side in model space, like in a real drawing: V1 at x 0, V2 at 100, V3 at 200, V4 at 300
areas = [sq('A1', 'V1', 0), sq('A2', 'V1', 10, layer='RULED'), sq('A3', 'V1', 20, layer='RULED'),
         sq('A4', 'V2', 100), sq('A5', 'V3', 200), sq('A6', 'V4', 300), sq('A7', 'V4', 310)]
labels = [{'kind': 'height', 'value': 3.1, 'unit_given': True, 'text': 'H=3.10m', 'at': (22, 2), 'layer': 'T', 'handle': 'h1'},
          {'kind': 'height', 'value': 5.6, 'unit_given': True, 'text': 'Н=560см', 'at': (302, 2), 'layer': 'T', 'handle': 'h2'},   # A6 (Cyrillic Н)
          {'kind': 'base', 'value': 0.45, 'unit_given': True, 'text': 'Z=0.45 m', 'at': (302, 2.5), 'layer': 'T', 'handle': 'h3'},
          {'kind': 'height', 'value': 9.0, 'unit_given': False, 'text': 'H=9', 'at': (100, 100), 'layer': 'T', 'handle': 'h4'}]
layermap = {'RULED': {'height_rule': 2.5, 'base_rule': 0.0}}
answers = {'accepted_views': ['V1', 'V2'], 'set': {'area:A7': {'height': 1.2, 'base': 0.0}}}
res, qs, conf, prop = H.resolve(areas, views, labels, layermap, answers, 'building')

ok = []
def check(name, cond, info=''):
    ok.append(cond); print(('PASS ' if cond else 'FAIL ') + name + (f'  ({info})' if info else ''))

check('title level parsing: %%P0.00 -> 0, +2.80 -> 2.8', H.title_level(views[0]['titles'])[0] == 0.0 and H.title_level(views[1]['titles'])[0] == 2.8)
check('Cyrillic Н=560см label parsed', H.HEIGHT_LABEL.match('Н=560см') is not None and H.num('560', 'см')[0] == 5.6)
check('A1: proposal accepted -> base 0, height 2.80 (to next level)', res['A1']['base'] == 0.0 and res['A1']['height'] == 2.8, res['A1']['height_source'])
check('A2: layer rule beats proposal (2.50)', res['A2']['height'] == 2.5 and 'layer rule' in res['A2']['height_source'])
check('A2: rule vs proposal difference is flagged', any(c['area'] == 'A2' and c['what'] == 'height' for c in conf))
check('A3: label beats layer rule (3.10)', res['A3']['height'] == 3.1 and res['A3']['height_source'].startswith('label'))
check('A3: label vs rule conflict flagged', any(c['area'] == 'A3' for c in conf))
check('A4: top floor -> no next level -> height needs answer', res['A4']['height'] is None and res['A4']['status'] == 'needs_answer' and res['A4']['base'] == 2.8)
check('A5: section view is not buildable', 'A5' not in res)
check('A6: labels give height 5.60 and base 0.45', res['A6']['height'] == 5.6 and res['A6']['base'] == 0.45 and res['A6']['top'] == 6.05)
check('A7: user answer for the area -> resolved', res['A7']['status'] == 'resolved' and 'user answer' in res['A7']['height_source'])
check('label outside every area is reported', any(c['what'] == 'label outside every buildable area' for c in conf))
check('questions list V2 (height missing)', any(q['view'] == 'V2' and q['missing'] == ['height'] for q in qs), qs)
r2, q2, _, _ = H.resolve(areas, views, labels, layermap, {'accepted_views': [], 'set': {}, 'auto_drawing_values': False}, 'building')
check('with automatic drawing values OFF and no acceptance, title levels are NOT used', r2['A1']['status'] == 'needs_answer' and r2['A1']['base'] is None)
r4, _, _, _ = H.resolve(areas, views, labels, layermap, {'accepted_views': [], 'set': {}}, 'building')
check('by default, title levels are used automatically and say so', r4['A1']['status'] == 'resolved'
      and 'automatic: read from the drawing' in r4['A1']['base_source'], r4['A1']['base_source'])
r3, q3, _, _ = H.resolve(areas, views, labels, layermap, dict(answers, skipped_views=['V2']), 'building')
check('skipped view: its areas are not built and not asked', 'A4' not in r3 and not any(q['view'] == 'V2' for q in q3))
print(f'\n{sum(ok)}/{len(ok)} passed'); sys.exit(0 if all(ok) else 1)
