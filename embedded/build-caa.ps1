param(
    [Parameter(Mandatory=$true)][string]$CatiaRoot,
    [Parameter(Mandatory=$true)][string]$SdkRoot,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
    [string]$Python = 'python',
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $EvidenceDirectory | Out-Null
& $Python "$PSScriptRoot/probe_environment.py" --catia-root $CatiaRoot --sdk-root $SdkRoot --output "$EvidenceDirectory/caa-preflight.json"
if ($LASTEXITCODE -ne 0) { throw 'CAA prerequisites unavailable. No module was installed or registered. See caa-preflight.json.' }
if ($CheckOnly) { return }
if (!(Get-Command mkGetPreq -ErrorAction SilentlyContinue)) { throw 'Run inside the matching CAA-RADE developer environment (mkGetPreq missing).' }
if (!(Get-Command mkrtv -ErrorAction SilentlyContinue)) { throw 'Matching CAA-RADE runtime generation tool mkrtv is missing.' }
Push-Location "$PSScriptRoot/caa"
try {
    & mkGetPreq -p ([IO.Path]::GetFullPath($SdkRoot))
    if ($LASTEXITCODE -ne 0) { throw 'Prerequisite resolution failed.' }
    & mkmk -a -u
    if ($LASTEXITCODE -ne 0) { throw 'CAA build failed. Preserve logs and correct against the installed matching SDK.' }
    & mkrtv
    if ($LASTEXITCODE -ne 0) { throw 'CAA runtime generation failed; do not register partial build outputs.' }
    $module = Join-Path $PSScriptRoot 'caa/win_b64/code/bin/PhyXiAgentUI.dll'
    if (!(Test-Path -LiteralPath $module)) { throw 'mkmk returned but no x64 module was found. This is not a successful build.' }
    Get-FileHash -LiteralPath $module -Algorithm SHA256 | ConvertTo-Json | Set-Content "$EvidenceDirectory/caa-module-hash.json" -Encoding UTF8
} finally { Pop-Location }
