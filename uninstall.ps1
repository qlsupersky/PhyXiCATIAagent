$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$configFile = Join-Path $root 'config.json'
if (!(Test-Path -LiteralPath $configFile)) { throw 'Run uninstall from the installed directory, not the distribution package.' }
$config = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
if ($root -ne [IO.Path]::GetFullPath($config.install_dir)) { throw 'Install path does not match config; refusing removal.' }
if ($root -eq [IO.Path]::GetPathRoot($root) -or $root -eq [Environment]::GetFolderPath('LocalApplicationData')) { throw 'Unsafe uninstall path.' }
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'PhyXiCATIAAgent.lnk'
if (Test-Path -LiteralPath $shortcut) {
    $shell = New-Object -ComObject WScript.Shell
    $target = $shell.CreateShortcut($shortcut).TargetPath
    if ($target -eq (Join-Path $root 'Launch.cmd')) { Remove-Item -LiteralPath $shortcut }
}
$documentShortcut = Join-Path $config.workspace '启动PhyXiCATIAAgent.lnk'
if (Test-Path -LiteralPath $documentShortcut) {
    $shell = New-Object -ComObject WScript.Shell
    if ($shell.CreateShortcut($documentShortcut).TargetPath -eq (Join-Path $root 'Launch.cmd')) {
        Remove-Item -LiteralPath $documentShortcut
    }
}
# Only known application files are removed. Workspace/model output is retained.
foreach ($name in @('opencode_link.py','opencode_panel.py','OPENCODE-LINK.md','native_images.py','native_examples.py','native_contract.py','native_gate.py','native_service.py','native_mcp.py','native_runtime.py','native_workflow.py','native_panel.py','NATIVE-MODELING.md','AUTOMATIC-EXECUTION.md','app.py','agent.py','responses_api.py','server_chat.py','server_connection.py','deepseek_connection.py','cc_switch.py','housing.py','section_analysis.py','vision_inputs.py','controller.py','templates.py','worker.py','automotive.py','surfaces.py','style_surfaces.py','REFERENCE-SURFACE-BRIEF.md','surface_quality.py','SURFACE-DEMO-BRIEF.md','providers.py','sessions.py','design_inputs.py','requirements.txt','build.ps1','README.md','LICENSE-NOTICE.md','Launch.cmd','config.json','config.before-update.json')) {
    $path = Join-Path $root $name
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
}
foreach ($folder in @('bin','bridge','samples','macros','__pycache__')) {
    $target = [IO.Path]::GetFullPath((Join-Path $root $folder))
    if (!$target.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe cleanup path.' }
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse }
}
Write-Host "Removed application files from $root."
Write-Host "Preserved user models: $($config.workspace)"
Write-Host 'Python, SimpleCADAPI and its Codex skill remain installed. Remove the macro library reference from CATIA if added.'
