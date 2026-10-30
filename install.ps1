param(
    [string]$InstallDir = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PhyXiCATIAAgent\app'),
    [string]$Workspace = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PhyXiCATIAAgent'),
    [string]$Python = '',
    [switch]$SkipDependencies
)
$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$Workspace = [IO.Path]::GetFullPath($Workspace)
if ($InstallDir -eq $source) { throw 'InstallDir must differ from the package directory.' }
if (!$Python) {
    $Python = (& py -3.12 -c 'import sys; print(sys.executable)' 2>$null | Select-Object -Last 1)
}
if (!$Python -or !(Test-Path -LiteralPath $Python)) { throw 'Install Python 3.12 (x64) first, or pass -Python with a supported 3.10-3.13 interpreter.' }
& $Python -c 'import sys; assert (3,10) <= sys.version_info[:2] <= (3,13); assert sys.maxsize > 2**32; import tkinter'
if ($LASTEXITCODE -ne 0) { throw 'Python must be x64 3.10-3.13 with Tk support.' }
if (!$SkipDependencies) {
    & $Python -m pip install --user -r (Join-Path $source 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'SDK dependency installation failed.' }
}
& $Python -c "import simplecadapi, marimo; from importlib.metadata import version; assert version('simplecadapi') == '2.2.1'"
if ($LASTEXITCODE -ne 0) { throw 'SDK 2.2.1 is required. Omit -SkipDependencies to install it.' }
if (!(Test-Path -LiteralPath (Join-Path $source 'bin\opencode.exe'))) {
    & (Join-Path $source 'fetch-runtime.ps1')
}
& (Join-Path $source 'build.ps1')
if (!(Test-Path -LiteralPath $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir | Out-Null }
if (Test-Path -LiteralPath (Join-Path $InstallDir 'config.json')) {
    $previous = Get-Content -LiteralPath (Join-Path $InstallDir 'config.json') -Raw | ConvertFrom-Json
    if (!$PSBoundParameters.ContainsKey('Workspace') -and $previous.workspace) {
        $Workspace = [IO.Path]::GetFullPath($previous.workspace)
    }
}
# Preserve every differing installed artifact before replacing it, including old config backups.
$backupRoot = Join-Path (Split-Path -Parent $source) ('_migration\install-0.6.5-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
if (Test-Path -LiteralPath $InstallDir) {
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    Get-ChildItem -LiteralPath $InstallDir -Force | Where-Object { $_.Name -ne '__pycache__' } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $backupRoot $_.Name) -Recurse
    }
}
foreach ($name in @('app.py','agent.py','responses_api.py','server_chat.py','server_connection.py','deepseek_connection.py','cc_switch.py','controller.py','housing.py','templates.py','worker.py','automotive.py','surfaces.py','style_surfaces.py','REFERENCE-SURFACE-BRIEF.md','surface_quality.py','section_analysis.py','vision_inputs.py','SURFACE-DEMO-BRIEF.md','providers.py','sessions.py','design_inputs.py','requirements.txt','build.ps1','uninstall.ps1','README.md','LICENSE-NOTICE.md')) {
    Copy-Item -LiteralPath (Join-Path $source $name) -Destination (Join-Path $InstallDir $name) -Force
}
foreach ($folder in @('bin','bridge','samples')) {
    $dest = Join-Path $InstallDir $folder
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $source $folder) -File | ForEach-Object {
        $target = Join-Path $dest $_.Name
        # A live OpenCode engine can hold the identical executable open. Avoid
        # rewriting equal bytes; genuinely different binaries still fail visibly.
        if (!(Test-Path -LiteralPath $target) -or
            (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash -ne
            (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash) {
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    }
}
foreach ($name in @('native_contract.py','native_gate.py','native_service.py','native_mcp.py','native_runtime.py','native_workflow.py','native_panel.py','native_images.py','native_examples.py','opencode_link.py','opencode_panel.py','OPENCODE-LINK.md','NATIVE-MODELING.md','AUTOMATIC-EXECUTION.md')) {
    Copy-Item -LiteralPath (Join-Path $source $name) -Destination (Join-Path $InstallDir $name) -Force
}
& $Python -c 'import mcp, win32crypt'
if ($LASTEXITCODE -ne 0) { throw 'MCP/pywin32 dependencies missing; omit -SkipDependencies to install them.' }
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null
$config = @{ python=$Python; workspace=$Workspace; install_dir=$InstallDir; version='0.6.5'; llm_provider='DeepSeek 官方 API'; llm_base_url='https://api.deepseek.com'; llm_model='deepseek-flash'; server_base_url='http://127.0.0.1:8000/v1'; server_model='qwen3.8-base'; llm_temperature=1.0 }
if ($previous) {
    if ($previous.llm_provider) {
        $config.llm_provider=$previous.llm_provider
        if ($config.llm_provider -eq '自部署 Qwen（结构化文本）') { $config.llm_provider='自部署 Qwen（结构化图文）' }
        if ($previous.llm_base_url) { $config.llm_base_url=$previous.llm_base_url }
        if ($previous.llm_model) { $config.llm_model=$previous.llm_model }
        if ($previous.llm_cc_switch_provider_id) { $config.llm_cc_switch_provider_id=$previous.llm_cc_switch_provider_id }
        foreach ($field in @('server_base_url','server_model','deepseek_base_url','deepseek_model','llm_temperature','llm_context_tokens','native_gate_path','opencode_project')) {
            if ($null -ne $previous.$field) { $config[$field]=$previous.$field }
        }
        if ($previous.llm_cc_switch_profiles) { $config.llm_cc_switch_profiles=$previous.llm_cc_switch_profiles }
    }
}
$config | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $InstallDir 'config.json') -Encoding UTF8
$pythonw = Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
if (!(Test-Path -LiteralPath $pythonw)) { $pythonw=$Python }
$launch = "@echo off`r`ncd /d `"$InstallDir`"`r`n`"$pythonw`" `"$InstallDir\app.py`"`r`n"
[IO.File]::WriteAllText((Join-Path $InstallDir 'Launch.cmd'),$launch,[Text.Encoding]::Default)
$macros = Join-Path $InstallDir 'macros'
New-Item -ItemType Directory -Force -Path $macros | Out-Null
$vbsCommand = '"' + (Join-Path $InstallDir 'Launch.cmd') + '"'
$quotedCommand = $vbsCommand.Replace('"','""')
$macro = @"
Language="VBSCRIPT"
Sub CATMain()
  Dim shell
  Set shell = CreateObject("WScript.Shell")
  shell.Run "$quotedCommand", 0, False
End Sub
"@
[IO.File]::WriteAllText((Join-Path $macros 'PhyXiCATIAAgent.CATScript'),$macro,[Text.Encoding]::Default)
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'PhyXiCATIAAgent.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($startMenu)
$shortcut.TargetPath = Join-Path $InstallDir 'Launch.cmd'
$shortcut.WorkingDirectory = $InstallDir
$shortcut.Description = 'CATIA native modeling agent - OpenCode + MCP'
$shortcut.WindowStyle = 7
$shortcut.Save()
$documentShortcut = Join-Path $Workspace '启动PhyXiCATIAAgent.lnk'
$direct = $shell.CreateShortcut($documentShortcut)
$direct.TargetPath = Join-Path $InstallDir 'Launch.cmd'
$direct.WorkingDirectory = $InstallDir
$direct.Description = 'CATIA native modeling agent - OpenCode + MCP'
$direct.WindowStyle = 7
$direct.Save()
& $Python (Join-Path $InstallDir 'app.py') --self-check
if ($LASTEXITCODE -ne 0) { throw 'Installed panel self-check failed.' }
Write-Host "Installed: $InstallDir"
Write-Host "CATIA macro library directory: $macros"
Write-Host "Models and logs: $Workspace"
