param(
    [Parameter(Mandatory=$true)][string]$WebViewSdk,
    [Parameter(Mandatory=$true)][string]$OutputDir
)
$ErrorActionPreference = 'Stop'
# Run in an x64 MSVC developer shell. This does not establish CAA compatibility.
if ($env:VSCMD_ARG_TGT_ARCH -ne 'x64') {
    throw 'Open an x64 MSVC developer shell first (vcvars64.bat / VsDevCmd -arch=x64).'
}
$compiler = Get-Command cl.exe -ErrorAction Stop
$sdk = [IO.Path]::GetFullPath($WebViewSdk)
$out = [IO.Path]::GetFullPath($OutputDir)
foreach ($required in @('build/native/include/WebView2.h', 'build/native/x64/WebView2Loader.dll')) {
    if (!(Test-Path -LiteralPath (Join-Path $sdk $required))) {
        throw 'Extract the pinned official WebView2 SDK first; see README.md.'
    }
}
New-Item -ItemType Directory -Force -Path $out | Out-Null
$target = Join-Path $out 'PhyXiWebHost.dll'
if (Test-Path -LiteralPath $target) { throw 'Output DLL already exists. Choose a new OutputDir.' }
# Use the genuine Windows SDK EventToken.h, never the MinGW compatibility header.
& $compiler.Source /nologo /LD /O2 /EHsc /std:c++17 /MT /DUNICODE /D_UNICODE /D_WIN32_WINNT=0x0602 `
    "/I$sdk/build/native/include" "$PSScriptRoot/native/PhyXiWebHost.cpp" `
    "/Fo$out/PhyXiWebHost.obj" "/Fe$target" `
    /link ole32.lib user32.lib gdi32.lib uuid.lib "/IMPLIB:$out/PhyXiWebHost.lib"
if ($LASTEXITCODE -ne 0) { throw 'MSVC native host compilation failed.' }
Copy-Item -LiteralPath "$sdk/build/native/x64/WebView2Loader.dll" -Destination $out
# Some developer shells omit the PowerShell Utility module from PSModulePath.
$sha = [Security.Cryptography.SHA256]::Create()
$stream = [IO.File]::OpenRead($target)
try { $digest = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
finally { $stream.Dispose(); $sha.Dispose() }
[pscustomobject]@{ Algorithm='SHA256'; Hash=$digest; Path=$target }
