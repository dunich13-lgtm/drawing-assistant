# Read-only connection check: lists the drawings open in AutoCAD, which one is active, and units.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File tools\acad\acad_list_docs.ps1
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$acad = Get-Acad
"AutoCAD $($acad.Version) - idle: $($acad.GetAcadState().IsQuiescent)"
$active = $acad.ActiveDocument.Name
$units = @{0='unitless';1='inches';2='feet';4='mm';5='cm';6='m'}
foreach ($d in $acad.Documents) {
    $u = $d.GetVariable('INSUNITS')
    $mark = if ($d.Name -eq $active) { '*' } else { ' ' }
    "$mark $($d.Name)  | units: $($units[[int]$u]) ($u) | model-space entities: $($d.ModelSpace.Count) | $($d.FullName)"
}
