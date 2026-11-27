# One command for the whole Path 2 pipeline: AutoCAD drawing(s) -> 3D model in SketchUp (spec 002, NIN-12).
# Runs every stage in order and STOPS at each point where the user must decide (exit code 10), printing the
# questions. After the answers are recorded, run the same command again: finished stages are reused.
#   & tools\build_3d.ps1 -Project <name> [-DocNames '*plan*','*section*'] [-Refresh]
# Stages: setup -> geometry -> areas -> sections -> heights -> build data -> openings -> SketchUp build -> verify -> renders -> report
# -Refresh re-reads the drawings (new dumps) even if earlier dumps exist. DWGs are only read, never changed.
param([Parameter(Mandatory)][string]$Project, [string[]]$DocNames = @('*'), [switch]$Refresh)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$data = Join-Path $root "data\$Project"
$py = 'python'
function Step($name) { Write-Output ''; Write-Output "=== $name ===" }
function Stop-For-User($why) { Write-Output ''; Write-Output "STOP - needs the user: $why"; Write-Output "Then run again: & tools\build_3d.ps1 -Project $Project"; exit 10 }
function Json($file, $expr) {
    $p = Join-Path $data $file
    if (-not (Test-Path $p)) { return $null }
    & $py -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print($expr)" $p
}
function Run($cmd) { & $cmd[0] $cmd[1..($cmd.Length - 1)]; if ($LASTEXITCODE -ne 0) { throw "failed: $($cmd -join ' ')" } }

Step 'AutoCAD'
& (Join-Path $root 'tools\acad\acad_list_docs.ps1')

Step '1 setup (layer map + project settings)'
$confirmed = (Json 'project.json' "d.get('confirmed')") -eq 'True' -and (Json 'layermap.json' "d.get('confirmed')") -eq 'True'
if (-not $confirmed) {
    & (Join-Path $root 'tools\acad\acad_inventory_all.ps1') -Project $Project -DocNames $DocNames
    Run @($py, (Join-Path $root 'tools\project_setup.py'), $Project)
    Stop-For-User "confirm the layer map and project settings above (python tools\project_setup.py $Project --layer ... --profile ... then --confirm)"
}
Write-Output 'confirmed'

Step '2 geometry from AutoCAD'
$geoObj = Join-Path $data 'geometry_object.tsv'
$geoSec = Join-Path $data 'geometry_opening_section_view.tsv'
if ($Refresh -or -not (Test-Path $geoObj)) { & (Join-Path $root 'tools\acad\acad_geo_dump.ps1') -Project $Project } else { 'reused ' + $geoObj }
$hasSecLayers = (Json 'layermap.json' "sum(1 for v in d['layers'].values() if v['role'] in ('opening','section_view'))")
if ([int]$hasSecLayers -gt 0 -and ($Refresh -or -not (Test-Path $geoSec))) { & (Join-Path $root 'tools\acad\acad_geo_dump.ps1') -Project $Project -Roles opening,section_view }

Step '3 closed areas + views'
Run @($py, (Join-Path $root 'tools\areas.py'), $Project)
$warn = Json 'areas.json' "sum(1 for v in d['views'] if v.get('warning'))"
if ([int]$warn -gt 0) { Stop-For-User 'a view probably holds several plans (see WARNING above): rerun areas.py with a smaller --view-gap' }

Step '4 sections / facades (level scales)'
Run @($py, (Join-Path $root 'tools\sections.py'), $Project)

Step '5 heights'
Run @($py, (Join-Path $root 'tools\heights.py'), $Project)
$open = Json 'heights.json' "sum(1 for r in d['areas'].values() if r['status']!='resolved')"
if ([int]$open -gt 0) { Stop-For-User "$open areas have no base/height yet: answer the questions above (heights.py --accept / --set / --skip)" }

Step '6 build data'
Run @($py, (Join-Path $root 'tools\build_data.py'), $Project)
$check = Json 'build.json' "','.join(v['id'] for v in d['views'] if v.get('check'))"
$profile = Json 'project.json' "d.get('profile')"
if ($profile -eq 'building') {
    Step '7 openings (building profile)'
    Run @($py, (Join-Path $root 'tools\openings.py'), $Project)
    $unres = Json 'openings.json' "sum(1 for o in d['openings'] if o['sill'] is None or o['head'] is None)"
    if ([int]$unres -gt 0) { Stop-For-User "$unres openings need typical sill/head heights for this project (openings.py --set window.sill=.. --set window.head=.. --set door.sill=0 --set door.head=.. --set passage.sill=0 --set passage.head=..)" }
    $slab = Json 'building_answers.json' "d.get('slab_thickness_m')"
    if (-not $slab) { Stop-For-User 'slab thickness for this project (build_data.py --slab 0.2)' }
    Run @($py, (Join-Path $root 'tools\build_data.py'), $Project)
    $check = Json 'build.json' "','.join(v['id'] for v in d['views'] if v.get('check'))"
}
if ($check) { Write-Output "NOTE: placement of $check was found by footprint only - please check it in SketchUp (build_data.py --confirm-placement $check)" }

Step '8 SketchUp build'
& (Join-Path $root 'tools\sketchup\su_query.ps1') -Code "SuBridge.use('su_objects'); SuObjects.run('$Project')" -TimeoutSec 900
if ($LASTEXITCODE -ne 0) { Stop-For-User 'SketchUp did not answer: open SketchUp and load tools/sketchup/su_bridge.rb in the Ruby Console' }

Step '9 verify'
$verify = & (Join-Path $root 'tools\sketchup\su_query.ps1') -Code "SuObjects.verify('$Project')" -TimeoutSec 600
$verify
$vline = (($verify -join "`n") -split "`n" | Where-Object { $_ -like 'checked*' } | Select-Object -First 1)

Step '10 renders'
$bb = Json 'build.json' "' '.join(str(round(v,1)) for v in [min(p[0] for e in d['elements'] for p in e['outline']), min(p[1] for e in d['elements'] for p in e['outline']), max(p[0] for e in d['elements'] for p in e['outline']), max(p[1] for e in d['elements'] for p in e['outline']), max(e['top'] for e in d['elements'])])"
$b = $bb -split ' ' | ForEach-Object { [double]$_ }
$cx = ($b[0] + $b[2]) / 2; $cy = ($b[1] + $b[3]) / 2; $span = [Math]::Max($b[2] - $b[0], $b[3] - $b[1])
$ci = [Globalization.CultureInfo]::InvariantCulture
$f = { param($v) ([double]$v).ToString('0.##', $ci) }
$eye = "[$(& $f ($cx - $span)), $(& $f ($cy - 1.3 * $span)), $(& $f ($b[4] + 0.6 * $span))]"
$tgt = "[$(& $f $cx), $(& $f $cy), $(& $f ($b[4] / 3))]"
& (Join-Path $root 'tools\sketchup\su_query.ps1') -Code "SuBridge.use('su_shots'); Shots.perspective('${Project}_overview', $eye, $tgt, 45, 1600, 1000)" -TimeoutSec 300

Step '11 report'
& $py (Join-Path $root 'tools\build_report.py') $Project "verify: $vline" | Select-Object -First 3; if ($LASTEXITCODE -ne 0) { throw 'report failed' }
Write-Output ''
Write-Output "DONE - model built in SketchUp (not saved). Report: data\$Project\build_report.md  Render: views\${Project}_overview.png"
