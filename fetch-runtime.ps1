param()
$ErrorActionPreference = 'Stop'
$runtimeRoot = $PSScriptRoot
$runtimeExe = Join-Path $runtimeRoot 'bin\opencode.exe'
$expected = '298d15cf834f828ce85650ab42677061d8a9697686c7e6bb4852bf21a0ff7f23'
if ((Test-Path -LiteralPath $runtimeExe) -and (Get-FileHash -LiteralPath $runtimeExe -Algorithm SHA256).Hash.ToLowerInvariant() -eq $expected) {
    Write-Host 'Pinned OpenCode 2.0.20 runtime already verified.'
    return
}
if (Test-Path -LiteralPath $runtimeExe) { throw 'Existing runtime hash differs. Preserve it and move it aside before fetching the pinned runtime.' }
$runtimeTemp = Join-Path ([IO.Path]::GetTempPath()) ('phyxi-runtime-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $runtimeTemp | Out-Null
$runtimeArchive = Join-Path $runtimeTemp 'runtime.tgz'
# Pinned official npm package. Verify the executable before placing it in bin.
Invoke-WebRequest -UseBasicParsing -Uri 'https://registry.npmjs.org/@opencode/cli-windows-x64/-/cli-windows-x64-2.0.20.tgz' -OutFile $runtimeArchive
& tar -xzf $runtimeArchive -C $runtimeTemp
if ($LASTEXITCODE -ne 0) { throw 'Cannot extract runtime; tar is required.' }
$runtimeCandidate = Get-ChildItem -LiteralPath $runtimeTemp -Recurse -Filter opencode.exe -File | Select-Object -First 1
if (!$runtimeCandidate -or (Get-FileHash -LiteralPath $runtimeCandidate.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'Pinned runtime SHA-256 mismatch.' }
New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot 'bin') | Out-Null
Copy-Item -LiteralPath $runtimeCandidate.FullName -Destination $runtimeExe
Write-Host 'Verified OpenCode 2.0.20 runtime installed. Download cache:' $runtimeTemp
