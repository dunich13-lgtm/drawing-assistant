"""Build report (spec 002 R6 / NIN-10): what was built, from where, every exclusion, gap, conflict and check.
Usage: python tools/build_report.py <project> ["<verify line from SuObjects.verify>"]  -> data/<project>/build_report.md
"""
import collections
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(project, verify=None):
    pdir = os.path.join(ROOT, 'data', project)
    b = json.load(open(os.path.join(pdir, 'build.json'), encoding='utf-8'))
    h = json.load(open(os.path.join(pdir, 'heights.json'), encoding='utf-8'))
    a = json.load(open(os.path.join(pdir, 'areas.json'), encoding='utf-8'))
    r = a['report']
    src = collections.Counter((e['view'], e['base_source'], e['height_source']) for e in b['elements'])
    md = [f'# Build report: {project}', '',
          f"**Built:** {b['counts']['elements']} elements from {b['counts']['areas_found']} closed areas · "
          f"**left out:** {b['counts']['excluded']} ({', '.join(f'{v} {k}' for k, v in b['counts']['excluded_by_reason'].items())})",
          '', '## Views (floors)', '', '| View | Title | Base → top | Elements | Placement |', '|---|---|---|---|---|']
    for v in sorted(b['views'], key=lambda v: v['base']):
        md.append(f"| {v['id']} | {v['title']} | {v['base']:+.2f} → {v['top']:+.2f} | {v['elements']} | "
                  f"{'⚠️ ' if v.get('check') else ''}{v['note']} |")
    md += ['', '## Where the heights come from', '', '| View | Base source | Height source | Elements |', '|---|---|---|---|']
    for (vid, bs, hs), n in sorted(src.items()):
        md.append(f'| {vid} | {bs} | {hs} | {n} |')
    md += ['', '## Drawing quality (area finder)', '',
           f"- gaps joined automatically (≤ {r['gap_tolerance_mm']} mm): {r['gaps_joined']}",
           f"- gaps 5–50 mm NOT joined, reported: {len(r['gaps_too_big'])}",
           f"- dangling line ends: {r['dangling_ends']} · overlapping lines: {r['overlapping_line_length_m']} m",
           f"- skipped entity types: {r['skipped'] or 'none'}"]
    md += ['', '## Conflicts and notes', '']
    md += [f"- {c['what']}: " + '; '.join(f"{o['value']} ({o['source']})" for o in c['other']) for c in h['conflicts']] or ['- none']
    md += ['', '## Checks', '', f'- {verify}' if verify else '- (run SuObjects.verify)',
           '- not saved: the SketchUp model is only saved when you ask', '',
           '## Assumptions to confirm',
           *[f"- {v['id']} ({v['title']}): placed by footprint overlap — check it sits right on the floor below" for v in b['views'] if v.get('check')],
           '- attic height 3.60 m runs to the roof level; the real attic walls end under the sloping roof (roof spec later)',
           f"- openings: {b['counts'].get('infill_pieces', 0)} sill/lintel pieces from typical heights confirmed for this project "
           f"(data/{project}/openings_answers.json); balcony doors to the floor are not told apart from windows yet",
           f"- window/door objects: {b['counts'].get('window_door_parts', 0)} parts (window = frame + glass, door = frame + "
           'closed leaf, passages left open); simple generic shapes, not the real window types',
           *([f"- stairs: left out ({json.load(open(os.path.join(pdir, 'building_answers.json'), encoding='utf-8'))['stairs_left_out']})"]
             if os.path.exists(os.path.join(pdir, 'building_answers.json')) and
             json.load(open(os.path.join(pdir, 'building_answers.json'), encoding='utf-8')).get('stairs_left_out') else
             ['- stairs: built from the plan drawings (see stairs.json); "PLEASE CHECK" where steps were added past the drawn end']),
           f"- slabs: {b['counts'].get('slabs', 0)}, thickness confirmed or measured in the sections, top at each floor level; "
           'walls still run floor-to-floor (they overlap the slab above by its thickness)',
           f"- facade elements: {b['counts'].get('facade', 0)} (roofs over lower parts, eaves overhang)" +
           ''.join(f'\n  - {n}' for n in b.get('facade_notes', []))]
    out = os.path.join(pdir, 'build_report.md')
    open(out, 'w', encoding='utf-8').write('\n'.join(md) + '\n')
    print('\n'.join(md))
    print('\n->', out)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
