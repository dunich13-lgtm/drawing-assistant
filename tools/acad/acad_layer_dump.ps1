# Read-only: model-space entities on the given layers (wildcards ok, comma list), via one filtered selection set (fast).
# Usage: & tools\acad\acad_layer_dump.ps1 -Layers 'A-WALL*,A-DOOR' [-DocName '*plan*'] [-Out walls]  -> data\<Out>.tsv
# Rows: L/P/A/C/T/B/D/H/X  layer  data...  (see AcadCommon.ps1 Get-EntityRow)
param([Parameter(Mandatory)][string]$Layers, [string]$DocName, [string]$Out = 'dwg_layer_dump')
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$doc = Get-AcadDoc $DocName
$nm = 'cc_layer_dump'
try { $doc.SelectionSets.Item($nm).Delete() } catch { }
$ss = $doc.SelectionSets.Add($nm)
[int16[]]$ft = @(8, 67); [object[]]$fd = @($Layers, 0)      # 67=0: model space only
$ss.Select(5, $null, $null, $ft, $fd)
$lines = New-Object System.Collections.Generic.List[string]
foreach ($e in $ss) { try { $lines.Add((Get-EntityRow $e -WithBox)) } catch { } }
$ss.Delete()
$p = Write-Tsv "$Out.tsv" $lines
"$($lines.Count) entities from $($doc.Name) -> $p"
