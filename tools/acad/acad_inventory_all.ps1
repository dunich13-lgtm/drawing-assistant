# Read-only: full inventory dump of every open drawing (or the ones matching -DocNames) for a project.
# Each drawing is made the active tab for its LISP dump, then the user's original active tab is restored.
# Usage: & tools\acad\acad_inventory_all.ps1 -Project myproject [-DocNames '*plan*','*section*']
#   -> data\<Project>\inventory\<drawing>.tsv   (then: python tools\project_setup.py <Project>)
param([Parameter(Mandatory)][string]$Project, [string[]]$DocNames = @('*'), [int]$TimeoutSec = 300)
. (Join-Path $PSScriptRoot 'AcadCommon.ps1')
$acad = Get-Acad
Assert-AcadIdle $acad
$safeProject = $Project -replace '[^A-Za-z0-9_\-]', '_'
$original = $acad.ActiveDocument
$docs = @(); foreach ($d in $acad.Documents) { foreach ($pat in $DocNames) { if ($d.Name -like $pat) { $docs += $d; break } } }
if ($docs.Count -eq 0) { throw "No open drawing matches $($DocNames -join ', ')." }
try {
    foreach ($d in $docs) {
        $acad.ActiveDocument = $d
        $safe = [IO.Path]::GetFileNameWithoutExtension($d.Name) -replace '[^A-Za-z0-9_\-]', '_'
        $exact = [Management.Automation.WildcardPattern]::Escape($d.Name)
        & (Join-Path $PSScriptRoot 'acad_run_lisp.ps1') -Lisp dwg_inventory.lsp -Call '(di-dump "{OUT}")' `
            -Out "$safeProject\inventory\$safe.tsv" -DocName $exact -TimeoutSec $TimeoutSec
    }
} finally {
    try { $acad.ActiveDocument = $original } catch { }
}
"Inventory of $($docs.Count) drawing(s) done. Next: python tools\project_setup.py $safeProject"
