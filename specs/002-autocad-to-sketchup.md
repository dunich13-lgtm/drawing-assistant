# 002 — Any 2D AutoCAD drawing → 3D objects in SketchUp (Path 2)

Status: agreed design, 2026-11-27 (grilled Q1–Q16) · Linear: project "Drawing assistant" (tickets via `/to-tickets`)
Pipeline reference: [docs/pipeline-autocad-sketchup.md](../docs/pipeline-autocad-sketchup.md)

## Goal
Claude turns whatever is drawn in AutoCAD — a building, an art installation, any object — into a
**3D visual model in SketchUp**, checks it against the drawing, and reports every mismatch and assumption.
Visual only (BIM is Path 1: PDF/DXF → Revit). Drawings come from many people, so **nothing may depend on
one way of drawing**: a wall can be 4 loose lines, a hatched rectangle, or open/closed polylines.

## Design decisions
| # | Decision |
|---|---|
| D1 | **Core is generic: closed areas + heights → 3D objects.** *Profiles* add meaning on top: first **building** (walls, door/window holes, slabs, floors); later installation, furniture, … |
| D2 | **Find closed areas however they are drawn.** All linework (lines, open/closed polylines, arcs, hatch boundaries) on object layers is one network: endpoints that touch are joined, crossing lines split, every closed area found. Pure geometry: exact, free, local. Layers are a hint, not a requirement. |
| D3 | **Gaps:** endpoints closer than **5 mm** (converted to drawing units; adjustable per project) are joined; bigger gaps are reported and the user is asked (they can be intentional). |
| D4 | **Areas inside areas:** own label → separate object (e.g. sculpture on a platform); building profile, no label → hole (courtyard, shaft); otherwise ask. |
| D5 | **What to ignore:** the project layer map lists the layers that hold objects; frames, title blocks, dimensions, text boxes and hatch patterns are excluded. Claude proposes the map, the user confirms once per project. |
| D6 | **Height AND base height**, first source that has it wins: (1) label inside the area (`H=56m`); (2) **section / elevation** in the drawing; (3) layer rule in the project map; (4) Claude's proposal, confirmed by the user; (5) ask the user. **Nothing gets a height that came from nowhere.** Disagreeing sources are flagged, never silently decided. |
| D7 | **Sections/elevations:** found by titles (РАЗРЕЗ, ФАСАДА, SECTION, ELEVATION), level marks (±0.00, +3.20 …) and vertical dimensions; linked to plan objects through the section cut line (A–A) and alignment; ask when the match is unclear. Each height names its source ("Section A-A, mark +3.20"). |
| D8 | **All open drawings** in AutoCAD can belong to the project (plan + sections in separate DWGs); Claude asks which ones belong. |
| D9 | **0.00 = the project's ±0.00 level mark.** All heights and bases relative to it. |
| D10 | **Version 1 shapes:** straight extrusions of any outline (curves included), each with its own base height. Tilted, twisted, freeform: a separate spec. |
| D11 | **Look:** plain colours per object type / layer; materials later. |
| D12 | **Run:** plain requests ("build this in 3D") first; a `/build-3d` skill once the loop is stable. |
| D13 | **Tests:** a generated test DXF only where it really helps the area-finding (gaps, overlaps, mixed styles); the user's real drawings prove it in practice. DWGs are always read-only. |

## Already done (tested live 2026-11-27)
- [x] Pipeline core: AutoCAD readers (COM + inline LISP), SketchUp bridge, builder base, inspect/probe, renders.
- [x] AutoCAD 2022 + SketchUp 2026 on this PC; LISP sent one form at a time (AutoCAD truncates long input).
- [x] Massing from labels (`massing_from_labels.py`, `su_massing.rb`): first case of D6(1) — closed polylines/circles + `H=..m`.

## Requirements

### R1 — First look and project setup
- [ ] Inventory of every open drawing (layers, blocks, texts, dimensions, units); Claude asks which drawings belong to the project (D8).
- [ ] Claude proposes `data/<project>/layermap.json` (object layers, ignored layers, layer rules) and `project.json` (units, ±0.00, gap tolerance, profile); the user confirms (D5).

### R2 — Area finder (`tools/areas.py`)
- [ ] Builds one planar network from lines, polylines (open or closed, with bulges), arcs, circles and hatch boundaries on object layers (D2).
- [ ] Joins endpoints within tolerance, splits at crossings, extracts every closed area with its holes (D3, D4).
- [ ] Reports: areas found, gaps joined, gaps too big, dangling lines, duplicates/overlaps.

### R3 — Heights (`tools/heights.py`)
- [ ] Labels inside areas (extends `massing_from_labels.py`).
- [ ] Sections/elevations: detect views, read level marks and vertical dimensions, link via cut lines and alignment (D7).
- [ ] Layer rules, Claude's proposals; questions for the rest. Every height and base carries its source; conflicts listed (D6).

### R4 — Builder (`tools/sketchup/su_objects.rb`)
- [ ] Extrudes every area from its base to its top, holes included, one named root group, re-runnable, one undo step (D10, D11).
- [ ] Tags/colours per type or layer.

### R5 — Building profile
- [ ] Classifies areas as walls / slabs / other (shape + layer + user confirmation); door and window holes from opening blocks or gaps in walls, heights from sections or labels; floors stacked by level marks.

### R6 — Verify and report
- [ ] Counts (areas found / built / skipped), probes at labels and level marks, renders: one perspective + plan cut, compared with the DWG.
- [ ] Report: what was built, the source of every height, every mismatch, gap and assumption. The SketchUp model is not saved and nothing is committed unless asked.

## Out of scope
- Writing to any DWG; saving the SketchUp model automatically.
- BIM data, schedules, quantities (Path 1 / Revit). Freeform / tilted shapes (own spec). Point clouds.

## Acceptance checks
1. A drawing mixing styles (4 loose lines, open polylines that meet, hatched shape, closed polyline, circle, a 3 mm gap, a 20 mm gap) gives the right closed areas; the 3 mm gap is joined, the 20 mm gap is reported.
2. On a real drawing from the user: after the layer map is confirmed, one request builds the 3D objects; every height has a named source; nothing unmapped is silently dropped.
3. A height read from a section matches the level mark; a label/section disagreement is flagged.
4. Plan render at the cut height overlays the DWG within ±1 cm; re-running rebuilds, Ctrl+Z removes a whole build.
5. Nothing from `data/`, `views/`, `bridge/` reaches GitHub.

## Tickets (Linear, project "Drawing assistant", created 2026-11-27)
| Ticket | Work | Blocked by |
|---|---|---|
| NIN-6 | Project setup: inventory of open drawings, layer map + project.json (R1) | — |
| NIN-7 | Area finder: network, gap joining, crossings, closed areas with holes, report (R2) | NIN-6 |
| NIN-8 | Heights from labels + layer rules + questions (R3, part 1) | NIN-7 |
| NIN-9 | Heights from sections/elevations (R3, part 2) | NIN-8 |
| NIN-10 | Generic object builder + verify/report (R4, R6) | NIN-8 |
| NIN-11 | Building profile: walls/slabs, openings, floors (R5) | NIN-9, NIN-10 |
| NIN-12 | End-to-end run on the user's real drawing (acceptance 2–4) | NIN-9, NIN-10 |
