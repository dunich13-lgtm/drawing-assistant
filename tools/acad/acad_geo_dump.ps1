# Read-only: geometry (with curves and hatch boundaries) of every model-space entity on the layers that the
# CONFIRMED project layer map gives a role (default: object).
# Usage: & tools\acad\acad_geo_dump.ps1 -Project venelin_r4 [-Roles object,opening] [-DocName '*plan*']
#   -> data\<Project>\geometry_<roles>.tsv   (parsed by tools/geom.py, used by tools/areas.py)
param([Parameter(Mandatory)][string]$Project, [string[]]$Roles = @('object'), [string]$DocName, [int]$TimeoutSec = 300)
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$lmPath = Get-DataPath "$Project\layermap.json"
if (-not (Test-Path $lmPath)) { throw "No layer map for $Project. Run the project setup first (NIN-6)." }
$lm = [IO.File]::ReadAllText($lmPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
if (-not $lm.confirmed) { throw "The layer map of $Project is not confirmed by the user yet." }
$names = @($lm.layers.PSObject.Properties | Where-Object { $Roles -contains $_.Value.role } | ForEach-Object { $_.Name })
if ($names.Count -eq 0) { throw "No layers with role $($Roles -join ',') in $Project." }
$lispList = "'(" + (($names | ForEach-Object { '"' + ($_ -replace '\\', '\\' -replace '"', '\"') + '"' }) -join ' ') + ")"
$out = "$Project\geometry_$($Roles -join '_').tsv"
"layers ($($names.Count)): $($names -join ' | ')"
& (Join-Path $PSScriptRoot 'acad_run_lisp.ps1') -Lisp dwg_block_geom.lsp -Call "(geo-dump $lispList `"{OUT}`")" -Out $out -DocName $DocName -TimeoutSec $TimeoutSec
