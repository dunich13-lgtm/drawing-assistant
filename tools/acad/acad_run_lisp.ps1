# Runs one of the read-only .lsp tools in AutoCAD and waits for its output file.
# The code is sent INLINE through SendCommand (not (load ...)), so AutoCAD's SECURELOAD dialog never blocks it.
# Bulk dumps this way take seconds where COM loops take minutes.
#
# Usage examples (the drawing must be the ACTIVE tab in AutoCAD; {OUT} becomes data\<Out> as a LISP path):
#   & tools\acad\acad_run_lisp.ps1 -Lisp dwg_inventory.lsp -Call '(di-dump "{OUT}")' -Out dwg_inventory.tsv
#   & tools\acad\acad_run_lisp.ps1 -Lisp dwg_block_geom.lsp -Call '(bg-dump "PLAN-1" "{OUT}")' -Out plan1_geom.tsv
#   & tools\acad\acad_run_lisp.ps1 -Lisp hatchloops.lsp -Call '(hl-dump "A-WALL*" "{OUT}")' -Out wall_hatches.txt
param(
    [Parameter(Mandatory)][string]$Lisp,
    [Parameter(Mandatory)][string]$Call,
    [Parameter(Mandatory)][string]$Out,
    [string]$DocName,
    [int]$TimeoutSec = 180
)
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$doc = Get-AcadDoc $DocName
$acad = Get-Acad
if ($acad.ActiveDocument.Name -ne $doc.Name) {
    throw "Make '$($doc.Name)' the active drawing tab in AutoCAD first (SendCommand runs in the active drawing)."
}

$lspPath = if (Test-Path $Lisp) { $Lisp } else { Join-Path $PSScriptRoot $Lisp }
$src = [IO.File]::ReadAllLines($lspPath, [Text.Encoding]::UTF8)
$code = ($src | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith(';') } | ForEach-Object { $_.Trim() }) -join ' '
if ($code.Contains("`t")) { throw "$Lisp contains a literal tab; use \t inside strings instead." }

$outPath = Get-DataPath $Out
if (Test-Path $outPath) { Remove-Item $outPath -Force }
$lispOut = ($outPath -replace '\\', '/') -replace '"', ''
$expr = $Call.Replace('{OUT}', $lispOut)
$doc.SendCommand("(progn $code $expr (princ))`n")

# Wait until the tool wrote its final #DONE line (AutoCAD runs the command asynchronously).
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $outPath) {
        try {
            $last = [IO.File]::ReadAllLines($outPath) | Select-Object -Last 1
            if ($last -like '#DONE*') { "OK $($doc.Name) -> $outPath ($last)"; exit 0 }
        } catch { }   # still being written / locked
    }
    Start-Sleep -Milliseconds 500
}
throw "Timed out after $TimeoutSec s waiting for $outPath. Check the AutoCAD command line for a LISP error, then press Esc there."
