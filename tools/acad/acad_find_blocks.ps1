# Read-only: block references in model space whose name matches a regex.
# Usage: & tools\acad\acad_find_blocks.ps1 -Pattern 'door|window' [-DocName '*plan*'] [-Out blocks]
# Rows: name  layer  insert x,y  rot_deg  sx,sy  bbox minx,miny maxx,maxy  attributes(tag=value|...)
param([string]$Pattern = '.', [string]$DocName, [string]$Out = 'dwg_blocks_found')
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$doc = Get-AcadDoc $DocName
$lines = New-Object System.Collections.Generic.List[string]
foreach ($e in $doc.ModelSpace) {
    try {
        if ($e.ObjectName -ne 'AcDbBlockReference') { continue }
        $n = $e.EffectiveName
        if ($n -notmatch $Pattern) { continue }
        $p = $e.InsertionPoint; $mn = $null; $mx = $null; $e.GetBoundingBox([ref]$mn, [ref]$mx)
        $att = @(); if ($e.HasAttributes) { foreach ($a in $e.GetAttributes()) { $att += "$($a.TagString)=$($a.TextString)" } }
        $lines.Add("$n`t$($e.Layer)`t$(F $p[0]),$(F $p[1])`t$(F ($e.Rotation * 180 / [Math]::PI))`t$(F $e.XScaleFactor),$(F $e.YScaleFactor)`t$(F $mn[0]),$(F $mn[1]) $(F $mx[0]),$(F $mx[1])`t$($att -join '|')")
    } catch { }
}
$p = Write-Tsv "$Out.tsv" $lines
"$($lines.Count) blocks in $($doc.Name) -> $p"
