<#
  Back up your Slack history (Windows).
  Examples:
    .\backup.ps1 -Enterprise -Pick                # interactively choose channels (asks about attachments)
    .\backup.ps1 -Enterprise                      # everything you're in
    .\backup.ps1 -Enterprise -NoFiles             # text only - skip attachments (much smaller)
    .\backup.ps1 -Enterprise -Pick -Estimate      # estimate disk size only (no downloads), then stop
    .\backup.ps1 -Enterprise -Fresh               # start a new archive instead of resuming
    .\backup.ps1 -DryRun                          # show the commands, don't run

  Backups are resumable + incremental: re-running continues an existing archive in data\archive.
#>
param(
  [switch]$Enterprise,
  [switch]$Pick,
  [string]$Workspace,
  [string[]]$Channels,
  [switch]$NoChannelsFile,
  [switch]$NoFiles,
  [switch]$Estimate,
  [switch]$Fresh,
  [switch]$NoPacing,
  [switch]$NoThreads,
  [string]$SkipStale,
  [int]$Months,
  [string]$Since,
  [switch]$AllTime,
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
if ($NoFiles)        { $cargs += "--no-files" }
if ($Estimate)       { $cargs += "--estimate" }
if ($Fresh)          { $cargs += "--fresh" }
if ($NoPacing)       { $cargs += "--no-pacing" }
if ($NoThreads)      { $cargs += "--no-threads" }
if ($SkipStale)      { $cargs += @("--skip-stale", $SkipStale) }
if ($PSBoundParameters.ContainsKey('Months')) { $cargs += @("--months", $Months) }
if ($Since)          { $cargs += @("--since", $Since) }
if ($AllTime)        { $cargs += "--all-time" }
if ($Out)            { $cargs += @("--out", $Out) }
if ($Yes)            { $cargs += "-y" }
if ($DryRun)     { $cargs += "--dry-run" }

$env:PYTHONPATH = $root
$env:PYTHONUTF8 = "1"
& $py @cargs
exit $LASTEXITCODE
