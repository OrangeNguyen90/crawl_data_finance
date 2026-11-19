$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& (Join-Path $projectRoot '.venv/Scripts/python.exe') manage.py run_collectors --schedule --retry-failed --max-jobs 4
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

