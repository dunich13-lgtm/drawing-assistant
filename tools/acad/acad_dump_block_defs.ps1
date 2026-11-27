# Read-only: dumps the geometry of block DEFINITIONS (incl. anonymous dynamic blocks like *U176) so Python can expand
# inserts (tools/blocks.py). Nested blocks are followed (up to -Depth levels).
# Usage: & tools\acad\acad_dump_block_defs.ps1 -Project venelin_r4 -Names '*U176','DOOR-90'  -> data\<p>\blocks\<name>.tsv
param([Parameter(Mandatory)][string]$Project, [Parameter(Mandatory)][string[]]$Names, [string]$DocName, [int]$Depth = 3)
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$todo = New-Object System.Collections.Generic.Queue[object]
foreach ($n in $Names) { $todo.Enqueue(@($n, 0)) }
$done = @{}
while ($todo.Count -gt 0) {
    $item = $todo.Dequeue(); $name = $item[0]; $level = $item[1]
    if ($done.ContainsKey($name)) { continue }
    $done[$name] = $true
    $safe = ($name -replace '[^\w\-]', '_')
    $out = "$Project\blocks\$safe.tsv"
    $esc = $name -replace '\\', '\\' -replace '"', '\"'
    & (Join-Path $PSScriptRoot 'acad_run_lisp.ps1') -Lisp dwg_block_geom.lsp -Call "(bg-dump `"$esc`" `"{OUT}`")" -Out $out -DocName $DocName -TimeoutSec 120 | Out-Null
    $path = Get-DataPath $out
    $nested = @(Get-Content $path -Encoding UTF8 | Where-Object { $_ -like 'INSERT*' } | ForEach-Object { ($_ -split "`t")[3] } | Sort-Object -Unique)
    "$name -> $out ($((Get-Content $path).Count - 1) entities$(if ($nested) { ', nested: ' + ($nested -join ', ') }))"
    if ($level + 1 -lt $Depth) { foreach ($n in $nested) { $todo.Enqueue(@($n, $level + 1)) } }
}
