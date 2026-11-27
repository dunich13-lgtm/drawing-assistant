# Path 2: AutoCAD drawing → SketchUp visual model

How Claude reads a drawing open in AutoCAD and builds and checks a visual model in SketchUp.
Generic version of Nick's pipeline (the "Ник's system" from the И4 course); the metro-project
code it came from is not part of this repo. Free tools only. (Path 1, PDF/DXF → Revit, uses the EE engine.)

```
AutoCAD (open DWG, READ-ONLY) ──COM (PowerShell) / inline AutoLISP──► data/*.tsv
      ──Python (tools/*.py)──► data/*.json  (build data in metres, every value with its DWG source)
      ──bridge (bridge/inbox → tools/sketchup/*.rb)──► SketchUp geometry
      ──renders (tools/sketchup/su_shots.rb)──► views/*.png ──► Claude looks, compares with the DWG, reports
```

The DWG is never written. Every SketchUp change is a re-runnable builder that erases its own named
root group and rebuilds it, as one undo step.

## Setup on this PC

| Needed | Status (checked 2026-11-27) |
|---|---|
| AutoCAD 2021 or newer (COM + `open ... "utf8"` in LISP) | AutoCAD 2022 installed |
| SketchUp with Ruby console | SketchUp 2026 installed |
| Python 3 (stdlib only for the core tools) | Python 3.12 |
| Windows PowerShell 5.1 | yes |

1. **Bridge (every new SketchUp session).** SketchUp → Extensions › Developer › Ruby Console:
   `load 'C:/Users/Nino/Drawing assistant/tools/sketchup/su_bridge.rb'`
   Done when `bridge/outbox/_bridge_started.out` appears. Then
   `tools\sketchup\su_query.ps1 -Code 'Sketchup.version'` answers `OK`.
2. **AutoCAD reachability.** Open the drawing, then run `tools\acad\acad_list_docs.ps1`.
   Done when it lists the drawing. "AutoCAD is busy" = the user is in a command: ask them to finish
   or press Esc. Never retry in a loop.

## Reading the DWG: two channels (both read-only)

| Channel | Use for | Tools |
|---|---|---|
| **COM from PowerShell** | Targeted reads: one layer, a window, texts, blocks by name, block definitions | `tools/acad/acad_*.ps1` (all take `-DocName`; with one drawing open it's used automatically) |
| **Inline AutoLISP via SendCommand** | Bulk dumps: every entity in the drawing (seconds instead of minutes), hatch boundaries, raw block geometry | `tools/acad/acad_run_lisp.ps1` + `dwg_inventory.lsp`, `dwg_block_geom.lsp`, `hatchloops.lsp` |

No PDF plotting: dimensions come from DIMENSION entities (`D` rows / `dims.csv`), and the model is
checked visually with SketchUp renders.

**Project setup (NIN-6) — do this first for every project:**
```powershell
& tools\acad\acad_inventory_all.ps1 -Project <name>          # dumps every open drawing (plan + section DWGs)
python tools\project_setup.py <name>                          # proposes layermap.json + project.json + questions
python tools\project_setup.py <name> --layer "A-WALL=object" --layer "SKULPT=object:3.2" --profile building --zero 0
python tools\project_setup.py <name> --confirm                # only after the user said yes
```
Output in `data/<name>/`: `layermap.json` (role per layer, reason, confidence, optional height rule),
`project.json` (units, scale to m, ±0.00 + source, gap tolerance, profile), `setup_summary.md`.
Unknown layers block the confirmation. Never confirm on the user's behalf.

**Closed areas (NIN-7) — after the setup is confirmed:**
```powershell
& tools\acad\acad_geo_dump.ps1 -Project <name>               # geometry of the object layers (curves, hatches, mirrored OCS)
python tools\areas.py <name> --plot                           # -> data\<name>\areas.json + views\<name>\areas_overview.png
python tools\areas.py <name> --plot-view V24                  # one view, with the too-big gaps circled in red
python tests\test_areas.py                                    # acceptance check 1: every drawing style
```
`areas.json`: views (plan / section / elevation / unknown, named by the nearest title) and every closed area
(explicit = drawn closed; cell = closed by loose linework) with view, layers, parent, area, perimeter, mean width,
holes, outline in metres; report: gaps joined, gaps too big (5–50 mm, ask), dangling ends, overlapping lines.

**Heights (NIN-8) and build (NIN-10):**
```powershell
python tools\heights.py <name>                                # resolve + questions (labels, rules, proposals)
python tools\heights.py <name> --accept V15,V12 --skip V1     # only after the user said yes
python tools\build_data.py <name>                             # build.json; stacks floors (shapes, else footprint = PLEASE CHECK)
& tools\sketchup\su_query.ps1 -Code "SuBridge.use('su_objects'); SuObjects.run('<name>')" -TimeoutSec 900
& tools\sketchup\su_query.ps1 -Code "SuObjects.verify('<name>')"     # every element vs its outline/levels (must be <= 1 cm)
python tools\build_report.py <name> "<verify line>"           # data\<name>\build_report.md
```

**First look at an unknown drawing (manual):**
```powershell
& tools\acad\acad_run_lisp.ps1 -Lisp dwg_inventory.lsp -Call '(di-dump "{OUT}")' -Out dwg_inventory.tsv
python tools\dwg_inventory.py data\dwg_inventory.tsv
```
→ `data/inventory/layers.csv, blocks.csv, texts.csv, dims.csv`: which layers hold walls, doors,
windows, levels and room names. From this Claude proposes a **layer map** for the project and the
user confirms it once.

Writing inline LISP: plain AutoLISP only (no `vl-*`), comments on their own lines only, no literal
tabs (use `\t` in strings), every prompt answered. Output files are opened with `(open path "w" "utf8")`.

## Driving SketchUp: the bridge

- **Protocol.** `su_query.ps1` writes `bridge/inbox/qNNNN.rb`; the bridge runs it once a second at top
  level and writes `bridge/outbox/qNNNN.out`: `OK` + result, or `ERROR …` + backtrace.
- **Load a tool in a query:** `SuBridge.use('su_inspect'); SuInspect.summary`
- **Builders** use `tools/sketchup/su_build_base.rb` (`SuBuild.run(root_name) { |b| ... }`): one
  operation, abort on any error, named root group erased and rebuilt, tags + materials, report string.
- **Inspecting:** `su_inspect.rb` — summary, element list, tag list, user's selection, faces, and
  `probe_down(x, y)` (raytest) to measure floors/ceilings. Hide the builder's own group first, and
  remember a ray hits faces from both sides (normal_z > 0.5 = floor, < −0.5 = ceiling).
- **Renders:** `su_shots.rb` — perspective, plan (temporary section plane) and section shots.
- **Camera rule.** `view.camera` is the live camera: copy it before a render and restore the copy
  after. The user works in the same window.
- **Textures.** Give a textured material only a texture; setting `.color` on it tints it.

## Task loop (each request)

1. **Read the request** (and screenshots). Name the objects; find them in the model (render or probe).
2. **Check the DWG**: the layers/blocks from the layer map, texts, dimensions. Done when every size,
   height and position has a DWG source, or is listed as an assumption.
3. **Data step** (`tools/<topic>.py` → `data/<topic>.json`): metres, source cited per value.
4. **Builder** (`tools/sketchup/su_<topic>.rb`): re-runnable, named root group, tag, report numbers.
5. **Verify**: renders from the user's angle and one or two others; numbers vs the DWG; camera restored.
6. **Report**: what was built, from where, every DWG/model mismatch, every assumption. The model is not
   saved and nothing is committed unless the user asks.

## Gotchas

**AutoCAD**
- A SendCommand that waits for input blocks COM until the user presses Esc.
- "Busy" / `RPC_E_CALL_REJECTED`: stop and ask the user; don't retry in a loop.
- PowerShell 5.1 scripts with non-ASCII text need a UTF-8 BOM. Keep the tool scripts ASCII.
- PowerShell unrolls COM collections: return one item with `,$x`. Write `[double]$v.Center[0] + 100`
  (the plain form fails on variant arrays).
- The same plan can exist several times in one drawing (block copies for floor, ceiling, overlays):
  find which copy you need before mapping coordinates.
- Drawing units: check INSUNITS (`acad_list_docs.ps1`); convert to metres in the data step.

**SketchUp**
- Move complex meshes rigidly (instance transform), never by shearing vertices.
- `make_unique` before editing nested instances.
- Inside one method, don't reuse a variable name that holds a path.

## Files

| Folder | Role |
|---|---|
| `tools/acad/` | AutoCAD readers: `AcadCommon.ps1` (shared), `acad_*.ps1` (COM), `*.lsp` + `acad_run_lisp.ps1` |
| `tools/sketchup/` | `su_bridge.rb`, `su_query.ps1`, `su_build_base.rb`, `su_inspect.rb`, `su_shots.rb` |
| `tools/*.py` | `geom.py` (parse dumps, hatch loops, bulges), `dwg_inventory.py` (drawing summary), `massing_from_labels.py` (closed shapes + "H=..m" labels → extrusion data) |

## Recipe: massing model from height labels (tested 2026-11-27)
```powershell
& tools\acad\acad_list_docs.ps1                                   # note the drawing units
& tools\acad\acad_layer_dump.ps1 -Layers '*' -Out massing_src      # or only the massing layers
python tools\massing_from_labels.py data\massing_src.tsv data\massing.json --units cm
& tools\sketchup\su_query.ps1 -Code "SuBridge.use('su_massing'); SuMassing.run"
```
Then verify: `SuInspect.probe_down(x, y, 100)` at each label (top = labelled height) and renders.
| `data/`, `views/`, `bridge/` | Working data, renders, bridge queues — gitignored, never pushed (client data) |
