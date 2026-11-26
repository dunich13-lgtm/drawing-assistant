# Checks the AI keys in .env with tiny FREE requests.
# Never prints the keys. Sends them only in request headers, never in URLs.
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File scripts\check-ai-keys.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root '.env'
if (-not (Test-Path $envFile)) { Write-Host 'No .env file found.'; exit 1 }

$cfg = @{}
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([A-Z_]+)\s*=(.*)$') { $cfg[$matches[1]] = $matches[2].Trim() }
}

function Get-ErrorText($err) {
    $resp = $err.Exception.Response
    if (-not $resp) { return $err.Exception.Message }
    $code = [int]$resp.StatusCode
    $msg = ''
    try { $msg = (New-Object IO.StreamReader($resp.GetResponseStream())).ReadToEnd() } catch {}
    if (-not $msg) { $msg = $err.ErrorDetails.Message }
    try { $j = $msg | ConvertFrom-Json; if ($j.error.message) { $msg = $j.error.message } } catch {}
    $msg = ($msg -replace '\s+', ' ').Trim()
    if ($msg.Length -gt 200) { $msg = $msg.Substring(0, 200) + '...' }
    return "HTTP $code $msg"
}

$prompt = 'Reply with the single word OK.'
$geminiOk = $false
$openrouterOk = $false

# ---------- Gemini (main) ----------
Write-Host '== Gemini (main) =='
$gKey = $cfg['GEMINI_API_KEY']
if (-not $gKey) {
    Write-Host '  GEMINI_API_KEY is empty - skipped.'
} else {
    $h = @{ 'x-goog-api-key' = $gKey }
    $models = @($cfg['GEMINI_MODEL']) + (($cfg['GEMINI_FALLBACK_MODELS'] -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $body = @{ contents = @(@{ parts = @(@{ text = $prompt }) }) } | ConvertTo-Json -Depth 6
    foreach ($m in $models) {
        try {
            $r = Invoke-RestMethod -Method Post -Headers $h -ContentType 'application/json' -Body $body `
                -Uri "https://generativelanguage.googleapis.com/v1beta/models/${m}:generateContent"
            Write-Host "  OK   $m answered: $($r.candidates[0].content.parts[0].text.Trim())"
            $geminiOk = $true
            break
        } catch {
            Write-Host "  busy $m - $(Get-ErrorText $_)"
        }
    }
    if (-not $geminiOk) { Write-Host '  No Gemini model answered right now (503 = Google overloaded; try again later).' }
}

# ---------- OpenRouter (backup, free models only) ----------
Write-Host ''
Write-Host '== OpenRouter (backup, free models only) =='
$oKey = $cfg['OPENROUTER_API_KEY']
if (-not $oKey) {
    Write-Host '  OPENROUTER_API_KEY is empty - skipped.'
} else {
    $h = @{ Authorization = "Bearer $oKey" }
    try {
        $k = (Invoke-RestMethod -Headers $h -Uri 'https://openrouter.ai/api/v1/key').data
        Write-Host "  Key valid. Free tier: $($k.is_free_tier). Usage so far: `$$($k.usage)"
        $oModel = $cfg['OPENROUTER_MODEL']
        if (-not $oModel -or $oModel -eq 'auto-free') {
            $candidates = ((Invoke-RestMethod -Uri 'https://openrouter.ai/api/v1/models').data | Where-Object { $_.id -like '*:free' }).id
        } else {
            $candidates = @($oModel)
        }
        $tried = 0
        foreach ($m in $candidates) {
            if ($m -notlike '*:free') { Write-Host "  skip $m - not a :free model (no-payment rule)"; continue }
            if ($tried -ge 6) { break }
            $tried++
            $body = @{ model = $m; max_tokens = 200; messages = @(@{ role = 'user'; content = $prompt }) } | ConvertTo-Json -Depth 5
            try {
                $r = Invoke-RestMethod -Method Post -Headers $h -ContentType 'application/json' -Body $body `
                    -Uri 'https://openrouter.ai/api/v1/chat/completions'
                Write-Host "  OK   $m answered: $("$($r.choices[0].message.content)".Trim())"
                $openrouterOk = $true
                break
            } catch {
                Write-Host "  busy $m - $(Get-ErrorText $_)"
            }
        }
        if (-not $openrouterOk) { Write-Host '  No free model answered. If errors mention providers/privacy, check openrouter.ai Settings > Privacy.' }
    } catch {
        Write-Host "  FAILED: $(Get-ErrorText $_)"
    }
}

Write-Host ''
Write-Host "Gemini: $(if ($geminiOk) {'working'} else {'not working right now'})   OpenRouter: $(if ($openrouterOk) {'working'} else {'not working right now'})"
if ($geminiOk -and $openrouterOk) { exit 0 } else { exit 1 }
