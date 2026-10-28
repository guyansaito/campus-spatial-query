$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
& "$Root\.venv\Scripts\python.exe" "$Root\scripts\seed.py" @args
exit $LASTEXITCODE
