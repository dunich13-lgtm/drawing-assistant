# Read-only: texts (TEXT / MTEXT / block attributes) matching a regex, in model space and optionally in named blocks.
# Usage: & tools\acad\acad_find_text.ps1 -Pattern 'kitchen|M 1:\d+' [-Blocks 'PLAN-1'] [-DocName '*plan*'] [-Out texts]
# Rows: owner  type  layer  x,y  text
param([Parameter(Mandatory)][string]$Pattern, [string[]]$Blocks = @(), [string]$DocName, [string]$Out = 'dwg_text_hits')
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$doc = Get-AcadDoc $DocName
$lines = New-Object System.Collections.Generic.List[string]
function Search-Texts($coll, $owner) {
    foreach ($e in $coll) {
        try {
            $o = $e.ObjectName
            if ($o -eq 'AcDbText' -or $o -eq 'AcDbMText') {
                $s = $e.TextString
                if ($s -match $Pattern) { $p = $e.InsertionPoint; $lines.Add("$owner`t$o`t$($e.Layer)`t$(F $p[0]),$(F $p[1])`t$($s -replace '\s+', ' ')") }
            } elseif ($o -eq 'AcDbBlockReference' -and $e.HasAttributes) {
                foreach ($a in $e.GetAttributes()) {
                    if ($a.TextString -match $Pattern) { $p = $e.InsertionPoint; $lines.Add("$owner`tATTRIB:$($e.EffectiveName)`t$($e.Layer)`t$(F $p[0]),$(F $p[1])`t$($a.TagString)=$($a.TextString)") }
                }
            }
        } catch { }
    }
}
Search-Texts $doc.ModelSpace 'MODEL'
foreach ($b in $Blocks) { Search-Texts $doc.Blocks.Item($b) $b }
$p = Write-Tsv "$Out.tsv" $lines
"$($lines.Count) hits in $($doc.Name) -> $p"
