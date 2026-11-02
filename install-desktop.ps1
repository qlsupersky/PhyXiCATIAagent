param()
$ErrorActionPreference = 'Stop'
$desktopRoot = Join-Path $PSScriptRoot 'desktop'
& npm.cmd ci --prefix $desktopRoot --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Electron installation failed. Check npm/network access.' }
Write-Host 'Electron ready. Run LaunchDesktop.cmd from the installed application.'
