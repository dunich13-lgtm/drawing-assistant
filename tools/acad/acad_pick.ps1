# Asks the user to click two opposite corners in AutoCAD (in the ACTIVE drawing) and saves the points.
# Use it to point Claude at an area or object. Changes nothing in the drawing.
# Usage: powershell -NoProfile -File tools\acad\acad_pick.ps1 <label>   -> data\acad_pick_<label>.json
param([string]$Label = 'pick', [string]$Project = '',
      [string]$Prompt1 = 'Click the FIRST corner (use object snap): ',
      [string]$Prompt2 = 'Click the OPPOSITE corner: ')
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$acad = Get-Acad
Assert-AcadIdle $acad
$u = $acad.ActiveDocument.Utility
$none = [System.Reflection.Missing]::Value
try {
    $p1 = $u.GetPoint($none, "`n[$Label] $Prompt1")
    # No base point: passing $p1 back through COM fails (DISP_E_EXCEPTION).
    $p2 = $u.GetPoint($none, "`n[$Label] $Prompt2")
} catch { Write-Error "Picking was cancelled or failed: $($_.Exception.Message)"; exit 1 }
if ($null -eq $p1 -or $null -eq $p2) { Write-Error 'No points received.'; exit 1 }
$u.Prompt("`n[$Label] Thanks - points sent to Claude.`n")
# (not named R: 'r' is a built-in alias for Invoke-History and would run instead)
function Format-Coord($v) { ([double]$v).ToString('R', $script:Ci) }
$json = '{{"label":"{0}","drawing":"{1}","p1":[{2},{3},{4}],"p2":[{5},{6},{7}],"picked_at":"{8}"}}' -f `
    $Label, ($acad.ActiveDocument.Name -replace '"', ''), (Format-Coord $p1[0]), (Format-Coord $p1[1]), (Format-Coord $p1[2]),
    (Format-Coord $p2[0]), (Format-Coord $p2[1]), (Format-Coord $p2[2]), (Get-Date -Format s)
$out = if ($Project) { Get-DataPath "$Project\acad_pick_$Label.json" } else { Get-DataPath "acad_pick_$Label.json" }
[IO.File]::WriteAllText($out, $json, (New-Object Text.UTF8Encoding $false))
$json
