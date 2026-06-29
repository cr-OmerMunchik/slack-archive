<#
  slack-archive setup (Windows / PowerShell)
  ------------------------------------------
  Downloads the slackdump binary, ensures Python + a virtual environment,
  and installs the Python dependencies. Run this once:

      powershell -ExecutionPolicy Bypass -File .\setup.ps1
#>
[CmdletBinding()]
param(
  [string]$SlackdumpVersion = "v4.4.1"   # pinned, known-good; bump to upgrade
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$bin  = Join-Path $root "bin"

function Info($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "!!  $m" -ForegroundColor Yellow }

# --- 1. slackdump binary --------------------------------------------------
$arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x86_64" }
$asset = "slackdump_Windows_$arch.zip"
$sdExe = Join-Path $bin "slackdump.exe"

if (Test-Path $sdExe) {
  Info "slackdump already present ($bin\slackdump.exe) - skipping download."
} else {
  New-Item -ItemType Directory -Force -Path $bin | Out-Null
  $base = "https://github.com/rusq/slackdump/releases/download/$SlackdumpVersion"
  $zip  = Join-Path $bin $asset
  $sums = Join-Path $bin "checksums.txt"
  Info "Downloading slackdump $SlackdumpVersion ($asset) ..."
  Invoke-WebRequest -Uri "$base/$asset" -OutFile $zip
  Invoke-WebRequest -Uri "$base/checksums.txt" -OutFile $sums

  $expected = (Select-String -Path $sums -Pattern ([regex]::Escape($asset))).Line.Split(" ")[0].Trim()
  $actual   = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
  if ($expected -and ($expected -ne $actual)) { throw "Checksum mismatch for $asset" }
  Info "Checksum OK."
  Expand-Archive -Path $zip -DestinationPath $bin -Force
  Remove-Item $zip
  Unblock-File -Path $sdExe
  Info "slackdump installed."
}

# --- 2. Python ------------------------------------------------------------
function Resolve-Python {
  foreach ($c in @("python", "py")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) {
      try {
        $v = & $cmd.Source -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
        if ($v -and [version]$v -ge [version]"3.9") { return $cmd.Source }
      } catch {}
    }
  }
  return $null
}

$py = Resolve-Python
if (-not $py) {
  Warn "Python 3.9+ not found. Attempting install via winget ..."
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    $py = Resolve-Python
  }
}
if (-not $py) {
  throw "Could not find or install Python 3.9+. Install it from https://www.python.org/downloads/ and re-run."
}
Info "Using Python: $py"

# --- 3. virtualenv + deps -------------------------------------------------
$venv = Join-Path $root ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
  Info "Creating virtual environment (.venv) ..."
  & $py -m venv $venv
}
$venvPy = Join-Path $venv "Scripts\python.exe"
Info "Installing Python dependencies ..."
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -m pip install --quiet -r (Join-Path $root "requirements.txt")

Write-Host ""
Info "Setup complete."
Write-Host @"
Next steps:
  1) Back up your Slack history:      .\backup.ps1
       (Enterprise Grid, e.g. Cybereason:  .\backup.ps1 -Enterprise -Workspace <subdomain>)
  2) Build the index + open search:   .\search.ps1
"@ -ForegroundColor Green
