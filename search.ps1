<#
  Build the search index (if needed) and open the local search UI (Windows).
  Examples:
    .\search.ps1                 # index if needed, then open browser
    .\search.ps1 -Reindex        # force a fresh index
    .\search.ps1 -Port 9000 -NoBrowser
#>
param(
  [switch]$Reindex,
  [switch]$NoBrowser,
  [int]$Port = 8731
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "Virtual env not found. Run .\setup.ps1 first."; exit 1 }

$env:PYTHONPATH = $root
$env:PYTHONUTF8 = "1"
$db = Join-Path $root "data\search.db"

if ($Reindex -or -not (Test-Path $db)) {
  & $py -m slackarchive index
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$serveArgs = @("-m", "slackarchive", "serve", "--port", $Port)
if ($NoBrowser) { $serveArgs += "--no-browser" }
& $py @serveArgs
exit $LASTEXITCODE
