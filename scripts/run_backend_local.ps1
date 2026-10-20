# Loads .env from the repo root and starts the verisearch backend on port 8010,
# wired to the local Docker stack (Postgres 5442, Redis 6389, OpenSearch 9200).

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$venvUvicorn = "C:\Users\hp\AppData\Local\pypoetry\Cache\virtualenvs\agentic-research-backend--mFwE2X6-py3.13\Scripts\uvicorn.exe"

# Load .env into the process environment
$envFile = Join-Path $root ".env"
Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
        $idx = $line.IndexOf("=")
        $key = $line.Substring(0, $idx).Trim()
        $val = $line.Substring($idx + 1).Trim()
        [Environment]::SetEnvironmentVariable($key, $val, "Process")
    }
}

Write-Host "DATABASE_URL = $env:DATABASE_URL"
Write-Host "REDIS_URL    = $env:REDIS_URL"
Write-Host "OPENSEARCH   = $env:OPENSEARCH_URL"

Set-Location $root
& $venvUvicorn backend.api_gateway.app:create_app --factory --host 0.0.0.0 --port 8010
