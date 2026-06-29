<#
  Search public channels by name so you can add them to channels.txt (Windows).
  Examples:
    .\find.ps1 -Enterprise incident
    .\find.ps1 -Enterprise "release"
#>
param(
  [Parameter(Mandatory = $true, Position = 0)][string]$Query,
  [switch]$Enterprise
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "Virtual env not found. Run .\setup.ps1 first."; exit 1 }

$cargs = @("-m", "slackarchive", "find-channels", $Query)
if ($Enterprise) { $cargs += "--enterprise" }

$env:PYTHONPATH = $root
$env:PYTHONUTF8 = "1"
& $py @cargs
exit $LASTEXITCODE
