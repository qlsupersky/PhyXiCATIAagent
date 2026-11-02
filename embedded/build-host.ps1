param(
    [Parameter(Mandatory=$true)][string]$WebViewSdk,
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [string]$Compiler = 'g++'
)
$ErrorActionPreference = 'Stop'
$sdk = [IO.Path]::GetFullPath($WebViewSdk)
$out = [IO.Path]::GetFullPath($OutputDir)
if (!(Test-Path -LiteralPath "$sdk/build/native/include/WebView2.h")) { throw 'Extract the pinned WebView2 SDK first; see README.md.' }
New-Item -ItemType Directory -Force $out | Out-Null
$target = Join-Path $out 'PhyXiWebHost.dll'
if (Test-Path -LiteralPath $target) { throw 'Output DLL already exists. Preserve it or choose a new OutputDir.' }
& $Compiler -shared -std=c++17 -O2 -DUNICODE -D_UNICODE -D_WIN32_WINNT=0x0602 `
    -I "$sdk/build/native/include" -I "$PSScriptRoot/native/compat" `
    "$PSScriptRoot/native/PhyXiWebHost.cpp" -o $target -lole32 -luuid -lgdi32 `
    -static-libgcc -static-libstdc++ -static -lwinpthread
if ($LASTEXITCODE -ne 0) { throw 'Native host compilation failed.' }
Copy-Item -LiteralPath "$sdk/build/native/x64/WebView2Loader.dll" -Destination $out
Get-FileHash -LiteralPath $target -Algorithm SHA256
