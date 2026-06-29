<#
  Back up your Slack history (Windows).
  Examples:
    .\backup.ps1                                  # member-only export (everything you're in)
    .\backup.ps1 -Enterprise -Workspace cybereason
    .\backup.ps1 -Enterprise -Channels C0123ABCD  # specific public channel(s) + channels.txt
    .\backup.ps1 -DryRun                           # show the slackdump command, don't run
#>
param(
  [switch]$Enterprise,
  [switch]$Pick,
  [string]$Workspace,
  [string[]]$Channels,
  [switch]$NoChannelsFile,
  [string]$Out,
  [switch]$Yes,
  [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Error "Virtual env not found. Run .\setup.ps1 first."; exit 1 }

$cargs = @("-m", "slackarchive", "backup")
if ($Enterprise) { $cargs += "--enterprise" }
if ($Pick)       { $cargs += "--pick" }
if ($Workspace)  { $cargs += @("--workspace", $Workspace) }
if ($Channels)       { $cargs += @("--channels") + $Channels }
if ($NoChannelsFile) { $cargs += "--no-channels-file" }
if ($Out)            { $cargs += @("--out", $Out) }
if ($Yes)            { $cargs += "-y" }
if ($DryRun)     { $cargs += "--dry-run" }

$env:PYTHONPATH = $root
$env:PYTHONUTF8 = "1"
& $py @cargs
exit $LASTEXITCODE
