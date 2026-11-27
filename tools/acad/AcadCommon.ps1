# Shared helpers for the AutoCAD readers. Dot-source it:  . (Join-Path $PSScriptRoot 'AcadCommon.ps1')
# Everything here is READ-ONLY towards the drawing. Works with AutoCAD 2021+ (COM ProgID 'AutoCAD.Application').
# Keep this file ASCII-only (Windows PowerShell 5.1 reads BOM-less files as ANSI).

$script:Ci = [Globalization.CultureInfo]::InvariantCulture
$script:RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$script:DataDir = Join-Path $script:RepoRoot 'data'

function F([object]$v, [string]$fmt = '0.####') { ([double]$v).ToString($fmt, $script:Ci) }

function Get-Acad {
    try { return [Runtime.InteropServices.Marshal]::GetActiveObject('AutoCAD.Application') }
    catch { throw 'AutoCAD is not running. Open AutoCAD with the drawing first.' }
}

function Assert-AcadIdle($acad) {
    # RPC_E_CALL_REJECTED / not quiescent = the user is in the middle of a command. Never retry in a loop.
    if (-not $acad.GetAcadState().IsQuiescent) { throw 'AutoCAD is busy: finish the current command or press Esc in AutoCAD, then try again.' }
}

# Picks the drawing to read. Never silently uses "whatever is active" when several drawings are open:
# the user may be working in another one.
function Get-AcadDoc([string]$DocName) {
    $acad = Get-Acad
    Assert-AcadIdle $acad
    $docs = @(); foreach ($d in $acad.Documents) { $docs += $d }
    if ($docs.Count -eq 0) { throw 'No drawing is open in AutoCAD.' }
    if ($DocName) {
        $hit = @($docs | Where-Object { $_.Name -like $DocName })
        if ($hit.Count -eq 0) { throw "No open drawing matches '$DocName'. Open: $(($docs | ForEach-Object Name) -join ', ')" }
        if ($hit.Count -gt 1) { throw "Several drawings match '$DocName': $(($hit | ForEach-Object Name) -join ', ')" }
        return ,$hit[0]
    }
    if ($docs.Count -eq 1) { return ,$docs[0] }
    throw "Several drawings are open, pass -DocName. Open: $(($docs | ForEach-Object Name) -join ', ')"
}

function Get-DataPath([string]$name) {
    if (-not (Test-Path $script:DataDir)) { New-Item -ItemType Directory $script:DataDir | Out-Null }
    Join-Path $script:DataDir $name
}

function Write-Tsv([string]$name, $lines) {
    $path = Get-DataPath $name
    [IO.File]::WriteAllLines($path, [string[]]$lines, (New-Object Text.UTF8Encoding $false))
    $path
}

# Row helpers shared by several readers: one line per entity, tab-separated, coordinates in drawing units.
function Get-EntityRow($e, [switch]$WithBox) {
    $o = $e.ObjectName; $l = $e.Layer
    $bb = ''
    if ($WithBox) { $mn = $null; $mx = $null; $e.GetBoundingBox([ref]$mn, [ref]$mx); $bb = "`t$(F $mn[0]),$(F $mn[1]) $(F $mx[0]),$(F $mx[1])" }
    switch ($o) {
        'AcDbLine'      { $a = $e.StartPoint; $z = $e.EndPoint; return "L`t$l`t$(F $a[0]),$(F $a[1]) $(F $z[0]),$(F $z[1])" }
        'AcDbPolyline'  { $c = $e.Coordinates; $pts = for ($i = 0; $i -lt $c.Length; $i += 2) { "$(F $c[$i]),$(F $c[$i+1])" }; return "P`t$l`t" + ($pts -join ' ') + $(if ($e.Closed) { ' C' } else { '' }) }
        'AcDbArc'       { $c = $e.Center; return "A`t$l`t$(F $c[0]),$(F $c[1])`t$(F $e.Radius)`t$(F $e.StartAngle)`t$(F $e.EndAngle)" }
        'AcDbCircle'    { $c = $e.Center; return "C`t$l`t$(F $c[0]),$(F $c[1])`t$(F $e.Radius)" }
        'AcDbText'      { $p = $e.InsertionPoint; return "T`t$l`t$(F $p[0]),$(F $p[1])`t$($e.TextString -replace '\s+', ' ')" }
        'AcDbMText'     { $p = $e.InsertionPoint; return "T`t$l`t$(F $p[0]),$(F $p[1])`t$($e.TextString -replace '\s+', ' ')" }
        'AcDbBlockReference' { $p = $e.InsertionPoint; return "B`t$l`t$($e.EffectiveName)`t$(F $p[0]),$(F $p[1])`t$(F ($e.Rotation * 180 / [Math]::PI))`t$(F $e.XScaleFactor),$(F $e.YScaleFactor)$bb" }
        { $_ -like 'AcDb*Dimension' } { return "D`t$l`t$(F $e.Measurement)$bb" }
        'AcDbHatch'     { return "H`t$l`t$($e.PatternName)$bb" }
        default         { return "X`t$l`t$o$bb" }
    }
}
