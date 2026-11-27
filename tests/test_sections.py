"""NIN-9 / acceptance check 3: section heights match level marks; label/section disagreement is flagged.
Run: python tests/test_sections.py"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import heights as H   # noqa: E402
import sections as S  # noqa: E402

ok = []
def check(name, cond, info=''):
    ok.append(cond); print(('PASS ' if cond else 'FAIL ') + name + (f'  ({info})' if info else ''))

# --- calibration (units cm, k = 0.01) -------------------------------------------------------------
k = 0.01
check('level text parsing', S.mark_value('%%P0.00') == 0.0 and S.mark_value('+2.80') == 2.8 and S.mark_value('-2.60') == -2.6
      and S.mark_value('%%P 0.00') == 0.0 and S.mark_value('кота') is None)
good = [(1000, 5000 + 280 * i, 2.8 * i, 't') for i in range(5)]                         # 1:1 section, zero at y 5000
row2 = [(1000, 9000 + 280 * i, 2.8 * i, 't') for i in range(5)]                         # same facade repeated 40 m higher
bad = [(3000, 5000, 0.0, 't'), (3000, 5300, 2.8, 't'), (3000, 5560, 5.6, 't')]          # 30 cm off at +2.80
cols = S.columns(good + row2 + bad, 0.5 / k, 15.0 / k)
check('repeated sheet rows are split into separate columns', len([c for c in cols if c[0][0] == 1000]) == 2)
titles = [{'text': 'РАЗРЕЗ А-А', 'at': (1200, 5500)}]
views, rejected = S.calibrate(cols, titles, k, 0.01, 30.0 / k)
v = [x for x in views if x['title'] == 'РАЗРЕЗ А-А']
check('calibrated: scale 1:1, zero at y 5000, residual 0', v and abs(v[0]['scale_m_per_unit'] - 0.01) < 1e-9
      and abs(v[0]['zero_y'] - 5000) < 1e-6 and v[0]['residual_mm'] == 0, v and (v[0]['scale_m_per_unit'], v[0]['zero_y']))
check('marks that do not fit within 1 cm are rejected', len(rejected) == 1 and rejected[0]['max_residual_mm'] > 10, rejected)

# --- heights: section = source 2 -----------------------------------------------------------------
def sq(aid, view, x, w=4.0):
    return {'id': aid, 'view': view, 'layers': ['WALL'], 'shape': [{'outline': [[x, 0], [x + w, 0], [x + w, w], [x, w]], 'holes': []}]}

pviews = [{'id': 'V1', 'kind': 'plan', 'titles': [{'text': 'План етаж 1 / кота %%P0.00'}]},
          {'id': 'V2', 'kind': 'plan', 'titles': [{'text': 'План етаж 2 / кота +2.80'}]},
          {'id': 'V3', 'kind': 'plan', 'titles': [{'text': 'План сутерен кота -2.60'}]}]
areas = [sq('A1', 'V1', 0), sq('A2', 'V1', 10), sq('A3', 'V2', 100), sq('A4', 'V3', 200)]
labels = [{'kind': 'height', 'value': 3.1, 'unit_given': True, 'text': 'H=3.10m', 'at': (12, 2), 'layer': 'T', 'handle': 'h1'}]
secs = [{'id': 'S1', 'title': 'Фасада Север', 'levels': [0.0, 2.8, 5.6]},
        {'id': 'S2', 'title': 'РАЗРЕЗ А-А', 'levels': [0.0, 2.8, 5.6]}]
res, qs, conf, _ = H.resolve(areas, pviews, labels, {}, {'accepted_views': [], 'set': {}, 'auto_drawing_values': False}, 'building', secs)
check('A1: base and height from the section, no proposal acceptance needed', res['A1']['status'] == 'resolved'
      and res['A1']['height'] == 2.8 and res['A1']['height_source'].startswith("section 'РАЗРЕЗ А-А'"), res['A1']['height_source'])
check('the section (РАЗРЕЗ) is preferred over a facade, and agreement is noted', '(+1 more level scales agree)' in res['A1']['base_source'])
check('A3: +2.80 -> next mark +5.60 = 2.80', res['A3']['base'] == 2.8 and res['A3']['height'] == 2.8)
check('A2: the label (3.10) wins over the section (2.80)', res['A2']['height'] == 3.1 and res['A2']['height_source'].startswith('label'))
check('A2: label/section disagreement is flagged', any(c['area'] == 'A2' and c['what'] == 'height'
      and any(o['source'].startswith('section') for o in c['other']) for c in conf))
check('A4: level -2.60 not in any section -> still a question (no proposal accepted)', res['A4']['status'] == 'needs_answer')
print(f'\n{sum(ok)}/{len(ok)} passed'); sys.exit(0 if all(ok) else 1)
