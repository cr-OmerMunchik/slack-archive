<#
  Generate an editable channels.txt listing the conversations you're in (Windows).
  Examples:
    .\pick.ps1 -Enterprise      # Slack Enterprise Grid (e.g. Cybereason)
    .\pick.ps1                  # standard workspace
#>
param([switch]$Enterprise)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "Virtual env not found. Run .\setup.ps1 first."; exit 1 }

$cargs = @("-m", "slackarchive", "pick-channels")
if ($Enterprise) { $cargs += "--enterprise" }

$env:PYTHONPATH = $root
$env:PYTHONUTF8 = "1"
& $py @cargs
exit $LASTEXITCODE
