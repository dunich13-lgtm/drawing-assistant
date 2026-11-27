# Read-only: geometry of named block DEFINITIONS (local block coordinates): inserts, polylines, lines, arcs, texts, hatches.
# Usage: & tools\acad\acad_dump_blocks.ps1 -Blocks 'PLAN-1','DOOR-90' [-DocName '*plan*']  -> data\dwgblk_<name>.tsv
param([Parameter(Mandatory)][string[]]$Blocks, [string]$DocName)
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$doc = Get-AcadDoc $DocName
foreach ($name in $Blocks) {
    $b = $doc.Blocks.Item($name)
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($e in $b) { try { $lines.Add((Get-EntityRow $e)) } catch { } }
    $safe = ($name -replace '[^A-Za-z0-9_]', '_')
    $p = Write-Tsv "dwgblk_$safe.tsv" $lines
    "$name -> $p ($($lines.Count) rows)"
}
