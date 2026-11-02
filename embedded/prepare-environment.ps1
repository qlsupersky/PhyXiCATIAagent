param(
    [Parameter(Mandatory=$true)][string]$BaseEnvironment,
    [Parameter(Mandatory=$true)][string]$CaaRuntimeDirectory,
    [Parameter(Mandatory=$true)][string]$HostDirectory,
    [Parameter(Mandatory=$true)][string]$AppDirectory,
    [Parameter(Mandatory=$true)][string]$Workspace,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$out = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $out) { throw 'Choose a NEW output directory to preserve existing environment/configuration files.' }
$caa = [IO.Path]::GetFullPath($CaaRuntimeDirectory)
$hostDir = [IO.Path]::GetFullPath($HostDirectory)
$appDir = [IO.Path]::GetFullPath($AppDirectory)
$workDir = [IO.Path]::GetFullPath($Workspace)
foreach ($file in @($BaseEnvironment,$Python,"$caa/code/bin/PhyXiAgentUI.dll","$caa/code/dictionary/PhyXiAgent.dic","$hostDir/PhyXiWebHost.dll","$hostDir/WebView2Loader.dll","$appDir/web_server.py")) {
    if (!(Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required compiled/runtime file missing: $file. Nothing was registered." }
}
foreach ($value in @($caa,$hostDir,$appDir,$workDir,$Python,$out)) {
    if ($value.Contains("`r") -or $value.Contains("`n")) { throw 'Multiline paths are unsupported.' }
}
$lines = [IO.File]::ReadAllLines([IO.Path]::GetFullPath($BaseEnvironment))
if (!($lines -match '^CATInstallPath=')) { throw 'Invalid CATIA base environment.' }
New-Item -ItemType Directory -Force $out | Out-Null
$config = Join-Path $out 'embedded-private.ini'
$profile = Join-Path $workDir 'embedded-webview2'
$ini = "[PhyXi]`r`nhost_dll=$hostDir\PhyXiWebHost.dll`r`npython=$Python`r`napp_dir=$appDir`r`nworkspace=$workDir`r`nwebview_profile=$profile`r`n"
[IO.File]::WriteAllText($config,$ini,[Text.Encoding]::Unicode)
$prefixes = @{CATDLLPath="$caa\code\bin"; CATDictionaryPath="$caa\code\dictionary"; CATMsgCatalogPath="$caa\resources\msgcatalog"}
$result = @()
foreach ($line in $lines) {
    $key = ($line -split '=',2)[0]
    if ($prefixes.ContainsKey($key)) { $result += "$key=$($prefixes[$key]);$(($line -split '=',2)[1])"; $prefixes.Remove($key) }
    elseif ($key -ne 'PHYXI_EMBEDDED_CONFIG') { $result += $line }
}
foreach ($key in $prefixes.Keys) { $result += "$key=$($prefixes[$key])" }
$result += "PHYXI_EMBEDDED_CONFIG=$config"
$envFile = Join-Path $out 'PhyXiCATIAAgent_Experimental.txt'
[IO.File]::WriteAllLines($envFile,$result,[Text.Encoding]::UTF8)
Write-Host "Prepared an isolated CATIA environment: $envFile"
Write-Host 'Original CATIA environment and installed plugin were not changed.'
Write-Host 'After all CAD calls finish and work is saved, start CATIA with CATSTART -run CNEXT -env PhyXiCATIAAgent_Experimental -direnv <this output directory>.'
Write-Host 'In CATIA enable the PhyXi Agent toolbar and click PhyXi Native Modeling. This CAA path still requires actual load validation.'
