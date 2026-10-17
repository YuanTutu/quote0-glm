$ErrorActionPreference = "Continue"

$projectRoot = $PSScriptRoot
$logDir = Join-Path $projectRoot "tmp"
$logPath = Join-Path $logDir "quote0-glm-scheduled.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Get-DotEnv {
    $envValues = @{}
    Get-Content -LiteralPath (Join-Path $projectRoot ".env") | ForEach-Object {
        $line = $_.Trim()
        if ($line -match '^export\s+([A-Za-z_][A-Za-z0-9_]*)="(.*)"\s*$') {
            $envValues[$matches[1]] = $matches[2]
        }
    }
    return $envValues
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content -LiteralPath $logPath -Value ""
Add-Content -LiteralPath $logPath -Value "[$stamp] start"

try {
    $envVals = Get-DotEnv
    foreach ($kv in $envVals.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($kv.Key, $kv.Value, "Process")
    }

    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $python = if (Test-Path $venvPython) { $venvPython } else { "python" }

    $output = & $python (Join-Path $projectRoot "quote0_glm.py") 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    Add-Content -LiteralPath $logPath -Value $output -Encoding UTF8
    $end = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$end] exit=$exitCode"
    exit $exitCode
}
catch {
    $end = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$end] error=$($_.Exception.Message)" -Encoding UTF8
    exit 1
}
