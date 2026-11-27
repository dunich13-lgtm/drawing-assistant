# Asks the user to click two opposite corners in AutoCAD (in the ACTIVE drawing) and saves the points.
# Use it to point Claude at an area or object. Changes nothing in the drawing.
# Usage: powershell -NoProfile -File tools\acad\acad_pick.ps1 <label>   -> data\acad_pick_<label>.json
param([string]$Label = 'pick')
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$acad = Get-Acad
Assert-AcadIdle $acad
$u = $acad.ActiveDocument.Utility
$none = [System.Reflection.Missing]::Value
try {
    $p1 = $u.GetPoint($none, "`n[$Label] Click the FIRST corner (use object snap): ")
    # No base point: passing $p1 back through COM fails (DISP_E_EXCEPTION).
    $p2 = $u.GetPoint($none, "`n[$Label] Click the OPPOSITE corner: ")
} catch { Write-Error "Picking was cancelled or failed: $($_.Exception.Message)"; exit 1 }
if ($null -eq $p1 -or $null -eq $p2) { Write-Error 'No points received.'; exit 1 }
$u.Prompt("`n[$Label] Thanks - points sent to Claude.`n")
function R($v) { ([double]$v).ToString('R', $script:Ci) }
$json = '{{"label":"{0}","drawing":"{1}","p1":[{2},{3},{4}],"p2":[{5},{6},{7}],"picked_at":"{8}"}}' -f `
    $Label, ($acad.ActiveDocument.Name -replace '"', ''), (R $p1[0]), (R $p1[1]), (R $p1[2]), (R $p2[0]), (R $p2[1]), (R $p2[2]), (Get-Date -Format s)
$out = Get-DataPath "acad_pick_$Label.json"
[IO.File]::WriteAllText($out, $json, (New-Object Text.UTF8Encoding $false))
$json
