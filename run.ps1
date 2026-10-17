$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

# 读取 .env（沿用 quote0-burnout 的 export KEY="value" 格式）
Get-Content -LiteralPath ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -match '^export\s+([A-Za-z_][A-Za-z0-9_]*)="(.*)"\s*$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
    }
}

# 优先用项目虚拟环境，退回系统 python
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

& $python "quote0_glm.py" @args
exit $LASTEXITCODE
