# Agent side of the SketchUp bridge: sends Ruby code to the running SketchUp and prints the result.
# Needs tools/sketchup/su_bridge.rb loaded in SketchUp's Ruby Console (once per SketchUp session).
# Usage:
#   & tools\sketchup\su_query.ps1 -Code 'Sketchup.active_model.title'
#   & tools\sketchup\su_query.ps1 -Code "SuBridge.use('su_inspect'); SuInspect.summary"
#   & tools\sketchup\su_query.ps1 -File my_builder_call.rb -TimeoutSec 300
# Exit code 0 = OK, 1 = Ruby error, 2 = bridge not answering.
param([string]$Code, [string]$File, [int]$TimeoutSec = 60)
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$inbox = Join-Path $root 'bridge\inbox'
$outbox = Join-Path $root 'bridge\outbox'
if (-not (Test-Path (Join-Path $outbox '_bridge_started.out'))) {
    Write-Output "Bridge not started. In SketchUp: Extensions > Developer > Ruby Console, run:"
    Write-Output "  load '$(($root -replace '\\','/'))/tools/sketchup/su_bridge.rb'"
    exit 2
}
if ($File) { $Code = [IO.File]::ReadAllText((Resolve-Path $File), [Text.Encoding]::UTF8) }
if (-not $Code) { throw 'Pass -Code or -File.' }

# Number queries upward: the highest number in the outbox is the last one used.
$nums = @(Get-ChildItem $outbox -Filter 'q*.out' -ErrorAction SilentlyContinue | ForEach-Object { if ($_.BaseName -match '^q(\d+)$') { [int]$matches[1] } })
$n = 1 + ($nums | Measure-Object -Maximum).Maximum
$name = 'q{0:D4}' -f $n
$enc = New-Object Text.UTF8Encoding $false
$tmp = Join-Path $inbox "$name.tmp"
[IO.File]::WriteAllText($tmp, $Code, $enc)
Move-Item $tmp (Join-Path $inbox "$name.rb")       # atomic rename: the bridge never sees a half-written file

$out = Join-Path $outbox "$name.out"
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $out) {
        Start-Sleep -Milliseconds 100
        $text = [IO.File]::ReadAllText($out, [Text.Encoding]::UTF8)
        Write-Output $text
        if ($text.StartsWith('OK')) { exit 0 } else { exit 1 }
    }
    Start-Sleep -Milliseconds 300
}
Write-Output "No answer after $TimeoutSec s ($name). Is SketchUp open with the bridge running, and not stuck in a dialog?"
exit 2
