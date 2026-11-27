# 001 — Project facts from documents → Revit (Path 1)

Status: agreed design, 2026-11-26 (grilled Q1–Q29 for NIN-5) · Linear: NIN-5 (tickets to be created)
Path 2 (AutoCAD → SketchUp visual model) is spec 002.

## Goal
Claude reads the raw documents of an architecture project — whatever mix arrives: PDFs, DWG/DXF, scans,
photos, later point clouds — and turns them into **project facts with a source on every value**, then
uses them to build the **Revit model** (EE engine), produce **documents** and **check** drawings.

Order of the four jobs (Q4): **D answer questions → C build Revit model → B produce documents → A check drawings.**
This spec details **D (version 1)** and fixes the interfaces for C, B and A.

## Design decisions
| # | Decision |
|---|---|
| D1 | Personal tool first (one user), team later (Q2). Runs inside Claude Code as plain requests / a command, no separate app (Q7). |
| D2 | **Inputs per project = one folder with any mix** of PDF, DWG/DXF, scans, photos, point clouds. Each source must work alone; several are combined (Q5, Q9, Q26). Command: `/project-facts <folder>`. |
| D3 | **Order of readers:** PDF first, then DWG/DXF, then scans/photos; **point clouds later** (8 GB RAM PC, Leica BLK files are large) — but the design keeps room for them (Q9, Q11). |
| D4 | **Exact first, AI second:** code reads vector PDF text/lines and DWG/DXF geometry; AI only for what code cannot read (scans, photos, messy drawings), and its results are marked "please check" (Q17). |
| D5 | **Privacy:** real client projects stay in local code + Claude (subscription). Free Gemini / OpenRouter only for test or public data (Q6, Q18). |
| D6 | **Version-1 facts:** rooms with areas; levels and heights; door and window counts; overall dimensions; built-up area and GFA; title-block data (name, address, investor, permit no., architect, year) (Q10, Q24). |
| D7 | **Room areas:** the value written on the drawing is the main value; the area calculated from geometry is the check; difference > **2 %** is flagged (Q27). |
| D8 | **Scale** read from title block / scale bar; **never guessed** — ask when missing (Q28). |
| D9 | **Trust:** every value has source (file + page/sheet) and confidence; uncertain values and conflicts between sources are marked and the user decides (Q12, Q16). |
| D10 | **Output:** a project note in the existing "Arch explanatory note" vault format — frontmatter fields unchanged (`project_name`, `gfa_m2`, `levels`, `door_count`, …) plus a new section **"Данни и източници"** (value / unit / source / confidence table + room list). Preview first; saved to the vault's `projects` only after approval; never overwrite without asking (Q13, Q20, Q23, Q29). |
| D11 | **Units metric.** Standards Bulgarian first; language and norms switchable for projects abroad (Q8, Q14). |
| D12 | **Tech:** Python in this repo; reuse ezdxf / shapely like the EE engine; free tools only (Q25). PDF reading needs a PDF library (PyMuPDF) — install only after the user's OK. |
| D13 | **C (Revit):** reuse the EE engine (`C:\EE_engine`, DXF → Revit 2026) if it is still the optimal path; look for something simpler first (Q15). |

## Requirements — version 1 (D: project facts)
### R1 — Project folder and inventory
- [ ] `/project-facts <folder>` lists every file, its type, pages/sheets, and which reader handles it.
### R2 — PDF reader (first)
- [ ] Vector PDFs: text with positions, lines/polylines, title block, scale; scanned pages detected and routed to the AI reader.
- [ ] Rooms (name + written area), level marks, door/window marks, dimensions, overall extents.
### R3 — DWG/DXF reader
- [ ] Same facts from DXF (ezdxf) and from open DWGs (Path 2 AutoCAD readers, read-only).
### R4 — Scan/photo reader (AI)
- [ ] Claude reads images for confidential projects; free Gemini only for test/public. Results marked "please check".
### R5 — Combine and check
- [ ] Merge facts from all sources; geometry area check (2 %); conflicts listed with both sources.
### R6 — Fact sheet
- [ ] Preview in chat → on approval write/update the vault note (frontmatter + "Данни и източници"); never overwrite silently.

## Later (separate specs, interfaces fixed here)
- **C:** facts + DXF → EE engine → Revit 2026 model (Existing phase).
- **B:** documents from the fact sheet (explanatory note template, door/window schedules, BOQ — existing Revit skills).
- **A:** checks before submission (missing dims, labels, plan vs schedule mismatches).
- **Point clouds** (Leica BLK, E57).

## Out of scope (v1)
Point clouds; writing to any DWG/PDF; paid AI services; imperial units.

## Acceptance checks
1. Test project **Venelin127**: PDFs plotted from its own DXFs (correct answers known from the EE engine outputs).
   From the PDFs alone the fact sheet lists rooms, areas, levels, door/window counts, dimensions, GFA — each with source + confidence.
2. The user checks it and it is correct; every difference explained.
3. A missing scale makes Claude ask instead of guessing; a 3 % area mismatch is flagged.
4. Nothing is written to the vault without approval; no client data reaches GitHub or free AI tiers.

## Known gaps
- The EE engine outputs give exact levels, walls and openings for Venelin127, but may not hold the room areas
  as written on the drawings — if not, the user checks those numbers once by hand.
- Making PDFs from the DXFs needs a plot step (ezdxf + matplotlib, or AutoCAD plot) — decide in the first ticket.

## Ticket outline (for `/to-tickets`)
1. Project folder inventory + reader routing (R1)
2. PDF reader: text, lines, title block, scale (R2) — incl. making test PDFs from Venelin127 DXFs
3. Facts from PDF: rooms + areas, levels, openings, dimensions, GFA (R2)
4. DXF/DWG reader reusing Path 2 tools + ezdxf (R3)
5. Combine + checks + conflicts (R5)
6. Fact sheet preview + vault note writer (R6)
7. Scan/photo reader (R4)
8. Acceptance run on Venelin127
