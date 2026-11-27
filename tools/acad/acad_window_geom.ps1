# Read-only: model-space geometry whose bounding box overlaps a world (WCS) window. Walks every entity (slow on
# very large drawings; prefer acad_layer_dump.ps1 when you know the layers).
# Usage: & tools\acad\acad_window_geom.ps1 -X0 0 -X1 20000 -Y0 0 -Y1 15000 [-DocName '*plan*'] [-Out area]
param([double]$X0 = -1e18, [double]$X1 = 1e18, [double]$Y0 = -1e18, [double]$Y1 = 1e18, [string]$DocName, [string]$Out = 'dwg_window_geom')
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$doc = Get-AcadDoc $DocName
$limited = ($X1 - $X0) -lt 1e17
$lines = New-Object System.Collections.Generic.List[string]
foreach ($e in $doc.ModelSpace) {
    try {
        $mn = $null; $mx = $null
        $e.GetBoundingBox([ref]$mn, [ref]$mx)
        if ($mx[0] -lt $X0 -or $mn[0] -gt $X1 -or $mx[1] -lt $Y0 -or $mn[1] -gt $Y1) { continue }
        if ($limited -and ($mx[0] - $mn[0]) -gt ($X1 - $X0) * 3) { continue }   # skip huge blocks (whole other plans)
        $lines.Add((Get-EntityRow $e -WithBox))
    } catch { }
}
$p = Write-Tsv "$Out.tsv" $lines
"$($lines.Count) entities from $($doc.Name) -> $p"
