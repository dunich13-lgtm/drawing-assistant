---
name: build-3d
description: Build a 3D SketchUp model from the drawing(s) open in AutoCAD (Path 2 of the Drawing assistant). Use when the user types /build-3d <project>, or asks to "build this drawing in 3D", "make the model in SketchUp", or to continue/rebuild an existing project (venelin_r4, harmanli, ...). Runs tools/build_3d.ps1, measures what the drawing contains, asks only what it can't, builds, verifies and reports.
---

# /build-3d <project>

Turns the drawing(s) open in AutoCAD into a verified 3D model in SketchUp, with as few questions as possible.
Full reference: `docs/pipeline-autocad-sketchup.md`. Spec: `specs/002-autocad-to-sketchup.md`.

## 0. Arguments and preconditions
- `<project>`: short ASCII name (e.g. `harmanli`). If missing: suggest one from the open drawing's name and ask.
  Existing projects live in `data/<project>/` (setup answers are reused; nothing is asked twice).
- AutoCAD open with the plan (and any separate section DWGs): `tools\acad\acad_list_docs.ps1`.
  Several unrelated drawings open → ask which belong, pass `-DocNames`.
- SketchUp open with the bridge: `tools\sketchup\su_query.ps1 -Code 'Sketchup.version'` must answer OK.
  If not, tell the user exactly: Extensions › Developer › Ruby Console →
  `load 'C:/Users/Nino/Drawing assistant/tools/sketchup/su_bridge.rb'`. A new project → suggest File › New first.

## 1. Run
```powershell
& tools\build_3d.ps1 -Project <project> *>&1 | Out-String -Width 220 | Set-Content -Encoding UTF8 data\<project>\run_log.txt
```
Read the log (it is long: filter for `=== |STOP|NOTE|ASK|WARNING|built|checked|DONE`). Exit code 0 = done, 10 = needs
the user, other = error (diagnose; AutoCAD "busy" → ask the user to press Esc, never retry in a loop).

## 2. When it stops (exit 10) — ask, record, rerun
Ask ONLY what the stop names, all open points in one round, each with a recommended answer (the user may answer
by voice: short, numbered, "yes" accepts the recommendation). Then record the answers and run step 1 again.

| Stop | What to show the user | Record with |
|---|---|---|
| setup not confirmed | `data/<p>/setup_summary.md`: layer roles, grouped; unknown layers with a recommendation each (usually ignore) | `python tools\project_setup.py <p> --layer "NAME=role" ... --profile building\|generic` then `--confirm` |
| several plans in one view | the WARNING line | `python tools\areas.py <p> --view-gap <smaller>` |
| areas without height | the questions printed by heights.py (per view, with the drawing's proposal) | `python tools\heights.py <p> --set view:V3:height=2.8` / `--skip V1` |
| openings not measurable | only the missing kinds (e.g. `door.head`) | `python tools\openings.py <p> --set door.head=2.1` |
| slab not measurable | one question | `python tools\build_data.py <p> --slab 0.2` |
| placement "PLEASE CHECK" (NOTE, not a stop) | after the build: ask the user to look in SketchUp | `python tools\build_data.py <p> --confirm-placement V4,V6` |

Placement the drawing can't tell: `tools\acad\acad_pick.ps1 -Project <p> -Label align_<view> -Prompt1 '1 of 2: ...' -Prompt2 '2 of 2: ...'`
(run in the background; tell the user first WHERE each plan is — a plot like `views/<p>/clicks_check.png` helps; the
build step rejects clicks outside the right plans).

## 3. Rules (never break)
- Values the drawing contains are used automatically (their source goes in the report). Never invent a value; never
  use a pure default without the user's yes. The user's explicit answers win over measurements.
- DWGs are read-only. SketchUp: only through the builders; never save the model unless asked.
- `data/`, `views/`, `bridge/` are client data: never commit or upload them.
- If a stage fails on a new drawing style, fix the tool generically (no project-specific hacks), rerun the tests
  (`python tests\test_areas.py`, `test_heights.py`, `test_sections.py`) and the other projects as regression.

## 4. Finish
Show the user: the overview render (`views/<p>_overview.png`, read it and check it first), one table per floor
(base → top, source), counts (walls, openings by kind, slabs), the verify line (must be "within 1 cm: all"), every
NOTE/disagreement from the log, the facade notes (roofs over lower parts, eaves: built or why left out), and what
is not built yet (sloping roofs; canopies/cladding drawn only in facades). Point to `data/<p>/build_report.md`. Remind: the SketchUp model is not saved.
