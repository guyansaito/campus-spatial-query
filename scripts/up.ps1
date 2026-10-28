$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}
docker compose up -d
docker compose ps
