$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$compiler = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (!(Test-Path -LiteralPath $compiler)) { throw '.NET Framework 4.x x64 C# compiler not found.' }
New-Item -ItemType Directory -Force -Path (Join-Path $root 'bin') | Out-Null
& $compiler /nologo /platform:x64 /r:Microsoft.CSharp.dll /r:System.Web.Extensions.dll "/out:$root\bin\CatiaBridge.exe" "$root\bridge\CatiaBridge.cs" "$root\bridge\SurfaceBuilder.cs" "$root\bridge\StyleSurfaceBuilder.cs"
if ($LASTEXITCODE -ne 0) { throw 'Bridge compilation failed.' }
