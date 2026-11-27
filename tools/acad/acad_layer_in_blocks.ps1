# Read-only: which block definitions hold entities on a layer (regex), with counts per entity type.
# Usage: & tools\acad\acad_layer_in_blocks.ps1 -Layer 'WALL' [-DocName '*plan*'] [-Out walls_in_blocks]
param([Parameter(Mandatory)][string]$Layer, [string]$DocName, [string]$Out = 'dwg_layer_in_blocks')
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$doc = Get-AcadDoc $DocName
$lines = New-Object System.Collections.Generic.List[string]
foreach ($b in $doc.Blocks) {
    if ($b.IsLayout -or $b.IsXRef) { continue }
    $n = 0; $types = @{}
    foreach ($e in $b) {
        try {
            if ($e.Layer -match $Layer) {
                $n++; $t = $e.ObjectName
                if ($t -eq 'AcDbBlockReference') { $t = "INSERT:$($e.EffectiveName)" }
                $types[$t] = 1 + [int]$types[$t]
            }
        } catch { }
    }
    if ($n -gt 0) { $lines.Add("$($b.Name)`t$n`t" + (($types.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join '; ')) }
}
$p = Write-Tsv "$Out.tsv" $lines
"$($lines.Count) blocks in $($doc.Name) -> $p"
