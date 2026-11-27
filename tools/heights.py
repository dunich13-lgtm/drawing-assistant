"""Heights and base levels for every area (spec 002 R3 part 1 / NIN-8, decisions D6, D9). Stdlib + shapely.

For each area that may be built (plan views and untitled views; sections/elevations are only read for heights),
BASE and HEIGHT are resolved separately; the first source that has a value wins:
  1. label inside the area        "H=56m", "h = 12.5 m", "Н=560см" (Cyrillic Н too) -> height
                                   "Z=+3.20", "B=0.45 m", "база=..."                 -> base
  2. section / elevation          a level scale in a section/facade (tools/sections.py) with a mark at the plan's
                                   level: base = that mark, height = the next mark up ("РАЗРЕЗ А-А: +2.80 -> +5.60")
  3. layer rule                    layermap.json height_rule / base_rule (metres)
  4. Claude's proposal, CONFIRMED  base = level in the view title ("План етаж 2 / кота +2.80");
                                   height = distance to the next plan level (+5.60 - +2.80 = 2.80)
  5. the user's answer             per view, layer or area (data/<project>/heights_answers.json)
An explicit answer for one AREA overrides everything (the user decides); any disagreement is listed as a conflict.
Nothing gets a value that came from nowhere: an area without base AND height is in the questions list.
All values are levels/lengths in metres relative to the project ±0.00.

Usage:
  python tools/heights.py <project>                                   resolve + print summary and questions
  python tools/heights.py <project> --accept V24,V19                  user confirmed Claude's proposals for these views
  python tools/heights.py <project> --set view:V1:height=1.2 --set "layer:010-Стени стб.:height=2.8,base=0"
  python tools/heights.py <project> --set area:A17:height=3.2,base=0.45
Output: data/<project>/heights.json
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))
import dwg_inventory as inv  # noqa: E402
from shapely import STRtree  # noqa: E402
from shapely.geometry import Point, Polygon  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIT = {'mm': 0.001, 'мм': 0.001, 'cm': 0.01, 'см': 0.01, 'm': 1.0, 'м': 1.0}
NUM = r'([+\-±]?\s*\d+(?:[.,]\d+)?)\s*(mm|cm|m|мм|см|м)?'
HEIGHT_LABEL = re.compile(r'^\s*[HhНн]\s*=\s*' + NUM + r'\s*$')
BASE_LABEL = re.compile(r'^\s*(?:[ZzBb]|база|base)\s*=\s*' + NUM + r'\s*$', re.I)
PM = r'(?:±|%%[pP]|\+/-)'
TITLE_LEVEL = re.compile(r'(?:кота|kote|level|ниво|niveau|elev\.?)\s*(' + PM + r'|[+\-])?\s*(\d+[.,]\d{1,3})', re.I)


def num(value, unit):
    v = float(value.replace(' ', '').replace(',', '.').replace('±', ''))
    return round(v * UNIT[unit.lower()] if unit else v, 6), bool(unit)


def title_level(views_titles):
    """Level of a view from its title, e.g. 'План етаж 2 / кота +2.80' -> 2.80; '%%P0.00' -> 0.0."""
    for t in views_titles:
        m = TITLE_LEVEL.search(t['text'])
        if m:
            sign = -1.0 if (m.group(1) or '').strip() == '-' else 1.0
            return sign * float(m.group(2).replace(',', '.')), t['text']
    return None, None


def read_labels(project, k):
    """Height/base labels in model space (TEXT/MTEXT and attributes of placed blocks), positions in metres."""
    labels = []
    for path in glob.glob(os.path.join(ROOT, 'data', project, 'inventory', '*.tsv')):
        for r in inv.load(path):
            if r[0] in ('*Model', '*SUB') and r[1] in ('TEXT', 'MTEXT', 'ATTRIB') and len(r) > 7:
                t = inv.clean(r[7])
                for kind, rx in (('height', HEIGHT_LABEL), ('base', BASE_LABEL)):
                    m = rx.match(t)
                    if m:
                        v, has_unit = num(m.group(1), m.group(2))
                        x, y = (float(c) * k for c in r[5].split(',')[:2])
                        labels.append({'kind': kind, 'value': v, 'unit_given': has_unit, 'text': t,
                                       'at': (x, y), 'layer': r[2], 'handle': r[3]})
    return labels


def section_levels(sections, plan_level, plan_levels=()):
    """Source 2: a section/facade level scale that has a mark at this plan's level (±1 cm).
    Sections also mark non-floor levels (window heads, beams, parapets), so the height does NOT run to the next mark:
      - to the next PLAN level when there is one (the section confirms it when it marks it too);
      - for the top floor: to the highest section mark within 6 m (roof / parapet edge), flagged 'please check'.
    -> (base, height) as (value, source) pairs, height may be None. Prefers a titled section (РАЗРЕЗ) over facades."""
    hits = [s for s in sections if any(abs(m - plan_level) <= 0.01 for m in s['levels'])]
    if not hits:
        return None
    hits.sort(key=lambda s: (0 if re.search(r'разрез|section|schnitt', s['title'], re.I) else
                             1 if not s['title'].startswith('untitled') else 2, s['id']))
    s = hits[0]
    more = f' (+{len(hits) - 1} more level scales agree)' if len(hits) > 1 else ''
    base = (plan_level, f"section '{s['title']}' ({s['id']}): mark {plan_level:+.2f}{more}")
    nxt = [l for l in plan_levels if l > plan_level + 0.01]
    if nxt:
        top = min(nxt)
        marked = [x for x in hits if any(abs(m - top) <= 0.01 for m in x['levels'])]
        src = (f"section '{marked[0]['title']}' ({marked[0]['id']}): marks {plan_level:+.2f} -> {top:+.2f} (next plan level)"
               if marked else f"next plan level {top:+.2f} (not marked in the section)")
        return base, (round(top - plan_level, 4), src)
    above = [(m, x) for x in hits for m in x['levels'] if plan_level + 0.01 < m <= plan_level + 6.0]
    if not above:
        return base, None
    m, x = max(above, key=lambda t: t[0])
    return base, (round(m - plan_level, 4),
                  f"section '{x['title']}' ({x['id']}): top floor up to its highest mark {m:+.2f} (roof/parapet edge) - PLEASE CHECK")


def resolve(areas, views, labels, layermap, answers, profile, sections=None):
    """Pure function: returns {area_id: result}, questions, conflicts.
    sections: level scales from tools/sections.py (height source 2)."""
    vkind = {v['id']: v['kind'] for v in views}
    skipped = set(answers.get('skipped_views', []))       # views the user chose not to build (roof plan, detail fragments)
    buildable = [a for a in areas if vkind.get(a['view']) not in ('section', 'elevation') and a['view'] not in skipped]
    # proposals per plan view: base = title level, height = next plan level - this level
    vlevel = {}
    for v in views:
        lv, src = title_level(v['titles'])
        if lv is not None and v['kind'] in ('plan', 'unknown'):
            vlevel[v['id']] = (lv, src)
    levels = sorted({lv for lv, _ in vlevel.values()})
    proposal = {}
    for vid, (lv, src) in vlevel.items():
        higher = [x for x in levels if x > lv + 1e-6]
        p = {'base': (lv, f"proposal: level in view title '{src}'")}
        if higher and profile == 'building':
            p['height'] = (round(higher[0] - lv, 4), f"proposal: next plan level {higher[0]:+.2f} - this level {lv:+.2f}")
        proposal[vid] = p

    # labels -> smallest buildable area that contains them
    polys = [Polygon(a['shape'][0]['outline'], a['shape'][0]['holes']) for a in buildable]
    tree = STRtree(polys) if polys else None
    by_area = collections.defaultdict(list)
    unplaced = []
    for lb in labels:
        p = Point(lb['at'])
        hits = [i for i in tree.query(p) if polys[i].contains(p)] if tree is not None else []
        if hits:
            by_area[buildable[min(hits, key=lambda i: polys[i].area)]['id']].append(lb)
        else:
            unplaced.append(lb)

    ans = {'area': {}, 'view': {}, 'layer': {}}
    for key, val in answers.get('set', {}).items():
        scope, _, target = key.partition(':')
        ans[scope][target] = val
    accepted = set(answers.get('accepted_views', []))

    results, conflicts = {}, []
    for a in buildable:
        aid = a['id']
        cand = {'base': [], 'height': []}            # (priority, value, source)
        for lb in by_area.get(aid, []):
            src = f"label '{lb['text']}' (layer {lb['layer']}, handle {lb['handle']})" + ('' if lb['unit_given'] else ', unit assumed m')
            cand[lb['kind']].append((1, lb['value'], src))
        if sections and a['view'] in vlevel:
            sec = section_levels(sections, vlevel[a['view']][0], levels)
            if sec:
                cand['base'].append((2, sec[0][0], sec[0][1]))
                if sec[1]:
                    cand['height'].append((2, sec[1][0], sec[1][1]))
        for lay in a['layers'][:1]:
            rule = layermap.get(lay, {})
            if rule.get('height_rule') is not None:
                cand['height'].append((3, float(rule['height_rule']), f"layer rule for '{lay}'"))
            if rule.get('base_rule') is not None:
                cand['base'].append((3, float(rule['base_rule']), f"layer rule for '{lay}'"))
        # Title levels are read from the drawing itself: used automatically (user, 2026-11-27), unless the project
        # switches it off ("auto_drawing_values": false); an explicit acceptance is still recorded as such.
        if a['view'] in accepted or answers.get('auto_drawing_values', True):
            for k2, (v, s) in proposal.get(a['view'], {}).items():
                tag = ' (confirmed by the user)' if a['view'] in accepted else ' (automatic: read from the drawing)'
                cand[k2].append((4, v, s.replace('proposal: ', 'drawing: ') + tag))
        for scope, target in (('view', a['view']), ('layer', a['layers'][0] if a['layers'] else None)):
            for k2 in ('base', 'height'):
                if target in ans[scope] and k2 in ans[scope][target]:
                    cand[k2].append((5, float(ans[scope][target][k2]), f'user answer for {scope} {target}'))
        if aid in ans['area']:
            for k2 in ('base', 'height'):
                if k2 in ans['area'][aid]:
                    cand[k2].append((0, float(ans['area'][aid][k2]), f'user answer for area {aid}'))
        res = {'view': a['view'], 'layers': a['layers'][:2]}
        for k2 in ('base', 'height'):
            c = sorted(cand[k2], key=lambda x: x[0])
            if c:
                res[k2], res[k2 + '_source'] = c[0][1], c[0][2]
                differ = [x for x in c[1:] if abs(x[1] - c[0][1]) > 0.005]
                if differ:
                    conflicts.append({'area': aid, 'what': k2, 'used': {'value': c[0][1], 'source': c[0][2]},
                                      'other': [{'value': x[1], 'source': x[2]} for x in differ]})
            else:
                res[k2], res[k2 + '_source'] = None, None
        if res['base'] is not None and res['height'] is not None:
            res['top'] = round(res['base'] + res['height'], 4)
            res['status'] = 'resolved'
        else:
            res['status'] = 'needs_answer'
        results[aid] = res

    # questions grouped by view: what is missing and what Claude proposes
    questions = []
    by_view = collections.defaultdict(list)
    for aid, r in results.items():
        if r['status'] == 'needs_answer':
            by_view[r['view']].append(aid)
    vt = {v['id']: (v['titles'][0]['text'] if v['titles'] else '') for v in views}
    for vid, ids in sorted(by_view.items(), key=lambda kv: -len(kv[1])):
        p = proposal.get(vid, {})
        missing = sorted({k2 for i in ids for k2 in ('base', 'height') if results[i][k2] is None})
        questions.append({'view': vid, 'title': vt.get(vid, ''), 'areas': len(ids), 'missing': missing,
                          'proposal': {k2: {'value': v, 'source': s} for k2, (v, s) in p.items()},
                          'proposal_complete': all(k2 in p for k2 in missing)})
    for lb in unplaced:
        conflicts.append({'area': None, 'what': 'label outside every buildable area',
                          'used': None, 'other': [{'value': lb['value'], 'source': lb['text'], 'at_m': [round(c, 3) for c in lb['at']]}]})
    return results, questions, conflicts, proposal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('project')
    ap.add_argument('--accept', help='comma-separated view ids whose proposals the user confirmed')
    ap.add_argument('--skip', help='comma-separated view ids the user chose NOT to build')
    ap.add_argument('--set', action='append', default=[], help='scope:target:key=val[,key=val]  scope = view | layer | area')
    a = ap.parse_args()
    pdir = os.path.join(ROOT, 'data', a.project)
    pj = json.load(open(os.path.join(pdir, 'project.json'), encoding='utf-8'))
    lm = json.load(open(os.path.join(pdir, 'layermap.json'), encoding='utf-8'))
    if not (pj.get('confirmed') and lm.get('confirmed')):
        sys.exit('Project setup is not confirmed yet (NIN-6).')
    ar = json.load(open(os.path.join(pdir, 'areas.json'), encoding='utf-8'))
    apath = os.path.join(pdir, 'heights_answers.json')
    answers = json.load(open(apath, encoding='utf-8')) if os.path.exists(apath) else {'accepted_views': [], 'set': {}}
    answers.setdefault('skipped_views', [])
    answers['view_ids_from'] = ar.get('source')            # view ids belong to this areas.json run
    if a.skip:
        answers['skipped_views'] = sorted(set(answers['skipped_views']) | {v.strip() for v in a.skip.split(',') if v.strip()})
    if a.accept:
        answers['accepted_views'] = sorted(set(answers['accepted_views']) | {v.strip() for v in a.accept.split(',') if v.strip()})
    for s in a.set:
        scope, _, rest = s.partition(':')
        target, _, kv = rest.rpartition(':')
        if scope not in ('view', 'layer', 'area') or not target:
            sys.exit(f'Bad --set {s!r}: use scope:target:key=val')
        vals = answers['set'].setdefault(f'{scope}:{target}', {})
        for pair in kv.split(','):
            key, _, val = pair.partition('=')
            if key not in ('base', 'height'):
                sys.exit(f'Bad key {key!r}: use base or height')
            vals[key] = float(val.replace(',', '.'))
    if a.accept or a.set or a.skip:
        json.dump(answers, open(apath, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    labels = read_labels(a.project, ar['units_to_m'])
    spath = os.path.join(pdir, 'sections.json')
    sections = json.load(open(spath, encoding='utf-8'))['views'] if os.path.exists(spath) else []
    results, questions, conflicts, proposal = resolve(ar['areas'], ar['views'], labels, lm['layers'], answers,
                                                      pj.get('profile'), sections)
    json.dump({'project': a.project, 'zero_level': pj.get('zero_level'), 'answers': answers, 'labels_found': len(labels),
               'proposals': {v: {k2: {'value': x, 'source': s} for k2, (x, s) in p.items()} for v, p in proposal.items()},
               'areas': results, 'questions': questions, 'conflicts': conflicts},
              open(os.path.join(pdir, 'heights.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    st = collections.Counter(r['status'] for r in results.values())
    src = collections.Counter((r['height_source'] or 'none').split(' (')[0].split(':')[0] for r in results.values())
    print(f"buildable areas {len(results)}: resolved {st['resolved']}, needs answer {st['needs_answer']} | "
          f"labels found {len(labels)} | conflicts {len(conflicts)}")
    print('height sources:', dict(src))
    for q in questions:
        prop = ', '.join(f"{k2} {v['value']:+.2f} ({v['source']})" for k2, v in q['proposal'].items()) or 'no proposal'
        print(f"  {q['view']:4} {q['areas']:4} areas missing {'+'.join(q['missing']):11} | {q['title'][:45]:45} | {prop}")


if __name__ == '__main__':
    main()
