# 002 — AutoCAD plan → SketchUp visual model (Path 2)

Status: draft, 2026-11-27 · Linear: project "Drawing assistant" (tickets to be created with `/to-tickets`)
Pipeline reference: [docs/pipeline-autocad-sketchup.md](../docs/pipeline-autocad-sketchup.md)

## Goal
When a plan is drawn in AutoCAD, Claude builds it as a **3D visual model in SketchUp** — walls,
openings (doors, windows), floor slabs — for **any project**, then checks the model against the drawing
and reports every mismatch and assumption. Visual only: no BIM data (that is Path 1, PDF/DXF → Revit).

One request, e.g. *"build the open plan in 3D"*, runs the whole loop; Claude only stops to ask about
real ambiguities (an unknown layer, a missing height).

## Already done (foundation, tested live 2026-11-27)
- [x] Generic pipeline core: AutoCAD readers (COM + inline LISP), SketchUp bridge, builder base, inspect/probe, renders.
- [x] AutoCAD 2022 + SketchUp 2026 work on this PC (LISP input is sent one form at a time — AutoCAD truncates long input).
- [x] Massing from height labels (`massing_from_labels.py` + `su_massing.rb`): closed outlines + "H=..m" texts → extrusions.

## Requirements

### R1 — First look at an unknown drawing
- [ ] Full inventory (`dwg_inventory.lsp` → `dwg_inventory.py`): layers, blocks, texts, dimensions, units.
- [ ] Claude summarises it in plain words: which layers look like walls, doors, windows, room names, levels.

### R2 — Layer map (per project, confirmed once)
- [ ] Claude **proposes** `data/<project>/layermap.json`: which layers / hatch patterns / block names mean
      RC wall, masonry wall, partition, door, window, slab outline, room name, level mark, and which to ignore
      (dimensions, furniture, annotation, hatching for finishes).
- [ ] The user **confirms or corrects** it; it is reused for every later run of that project.
- [ ] Nothing unmapped is silently dropped: it is listed in the report.

### R3 — Project settings
- [ ] `data/<project>/project.json`: drawing units (from INSUNITS), floor-to-floor height, wall height,
      slab thickness, default sill and head heights, which plan area/block is which floor.
- [ ] Values read from the drawing (level marks, texts, sections) win; anything defaulted is marked
      **assumption** in the report.

### R4 — Data step (`tools/plan_to_model.py` → `data/<project>/model.json`, metres)
- [ ] **Walls** from (in order of support): wall hatches (boundary loops), closed polylines on wall layers;
      later: pairs of parallel lines.
- [ ] **Openings** from block inserts on door/window layers: position, rotation, width (attribute, block
      name or block geometry), height/sill from attributes or project defaults.
- [ ] **Slabs** from the outer outline of each floor (or a slab layer if mapped).
- [ ] Every value carries its DWG source (layer, handle or dump line). Conflicts are flagged, not decided.

### R5 — Builders (SketchUp, one named root group each, re-runnable, one undo step)
- [ ] `su_walls.rb`: walls extruded to wall height, tag per wall type, material per type.
- [ ] `su_openings.rb`: cuts door/window holes in the walls; simple door leaf / glass pane as visual hint.
- [ ] `su_slabs.rb`: floor slabs at each level.
- [ ] Multiple floors stacked by floor-to-floor height.

### R6 — Verify and report
- [ ] Counts: walls, doors, windows built vs found in the DWG.
- [ ] Probes: wall heights, slab levels; renders: one perspective, plan cut at 1.0 m per floor, compared
      with the DWG plan.
- [ ] Report: what was built, from where, every mismatch, every assumption. The SketchUp model is not
      saved and nothing is committed unless the user asks.

## Out of scope
- Writing to the DWG (always read-only). Saving the SketchUp model automatically.
- BIM data, schedules, quantities (Path 1 / Revit). Roofs, stairs, furniture (later specs).
- Project-specific code (the metro-station tools stay out of this repo).

## Acceptance checks
1. On a real floor plan chosen by the user: after the layer map is confirmed, one request builds walls,
   openings and slab in SketchUp.
2. Counts match the DWG (every difference explained in the report).
3. Plan render at 1.0 m overlays the DWG plan within drawing tolerance (±1 cm).
4. Re-running rebuilds instead of duplicating; Ctrl+Z removes a whole build in one step.
5. Nothing from `data/`, `views/` or `bridge/` reaches GitHub.

## Open questions (recommended answer first — to confirm with the user)
1. **How are walls drawn in your plans?** Hatched walls / closed polylines / two parallel lines?
   → *Support hatches and closed polylines first* (exact outlines); parallel lines need wall-joining logic, later.
2. **Test drawing:** which real plan do we build first? → *A one-floor plan you know well, with doors as blocks.*
3. **Default heights** when the drawing has none → *wall 2.80 m, slab 0.20 m, door 2.10 m, window sill 0.90 m / head 2.10 m — all reported as assumptions.*
4. **Several floors in one DWG:** separate plan areas or blocks? → *Claude asks once per project which area is which floor, saved in project.json.*
5. **Command:** a slash command (e.g. `/build-3d`) or just asking in words? → *Asking in words first; a skill later, once the loop is stable.*
6. **Visual style:** plain colours per element type, or materials (concrete, plaster, glass)? → *Plain colours per type first.*

## Ticket outline (for `/to-tickets`)
1. Inventory summary + layer-map proposal/confirmation (R1, R2)
2. project.json + units/levels reading (R3)
3. Walls data step from hatches + closed polylines (R4)
4. Walls builder + verify (R5, R6)
5. Openings data step + builder with holes (R4, R5)
6. Slabs + multiple floors (R4, R5)
7. End-to-end run on the test plan + report (R6, acceptance)
