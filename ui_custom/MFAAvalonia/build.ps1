param(
    [string]$SourceDir = (Join-Path $PSScriptRoot '..\..\.tmp\MFAAvalonia-src'),
    [string]$DotnetExe = (Join-Path $PSScriptRoot '..\..\.tmp\mfa-build\.dotnet-sdk\dotnet.exe')
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$source = (Resolve-Path $SourceDir).Path
$dotnet = (Resolve-Path $DotnetExe).Path
$git = (Get-Command git -ErrorAction Stop).Source

if ($git -match '\\Espressif\\tools\\git\\(?:bin|cmd)\\git\.exe$') {
    $mingwGit = Join-Path (Split-Path (Split-Path $git -Parent) -Parent) 'mingw64\bin\git.exe'
    if (Test-Path -LiteralPath $mingwGit) {
        $git = $mingwGit
    }
}
$gitRuntimeDir = Split-Path $git -Parent
if (($env:Path -split ';') -notcontains $gitRuntimeDir) {
    $env:Path = "$gitRuntimeDir;$env:Path"
}
# 原生命令安全执行器：
# PowerShell 5.1 在 $ErrorActionPreference='Stop' 下，任何原生命令往 stderr 写东西
# 都会抛 NativeCommandError 并终止脚本（`2>$null` / `2>&1 | Out-Null` 都无效）。
# git apply --check 在「补丁已打过」时必然写 stderr，所以必须这样包一层：
# 执行期间放宽为 Continue，成败只看 $LASTEXITCODE。
function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$Quiet
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Quiet) {
            & $FilePath @Arguments 2>&1 | Out-Null
        } else {
            & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

# 换 exe 图标的两样必需品，缺任何一个都直接失败（失败关闭）：
# 静默跳过会造出「构建成功、图标却悄悄退回旧 logo」的假象。
# 放在编译之前，避免白等几分钟才报错。
# rcedit 全仓库只有这一份，.gitignore 里专门为它开了 ! 反例。
$rcedit = Join-Path $PSScriptRoot 'tools\rcedit-x64.exe'
$hostExe = Join-Path $projectRoot 'install\MFAAvalonia.exe'
if (-not (Test-Path -LiteralPath $rcedit)) {
    throw "缺少 rcedit：$rcedit`n（Windows 任务栏 / 资源管理器读的是宿主 exe 的内嵌图标，没有它换不了）"
}
if (-not (Test-Path -LiteralPath $hostExe)) {
    throw "缺少宿主 exe：$hostExe`n（先构建本地 install 运行镜像再跑本脚本）"
}

# Idempotency markers keyed by patch filename — order comes from patches.list.
$patchMarkers = @{
    'laa-chip-filter.patch' = @{ MarkerFile = 'MFAAvalonia\Features\ChipFilter\ChipFilterPlan.cs'; Marker = 'ChipFilterCatalog' }
    'laa-chip-filter-total-level.patch' = @{ MarkerFile = 'MFAAvalonia\Features\ChipFilter\ChipFilterPlan.cs'; Marker = 'MinimumTotalLevel' }
    'laa-chip-task-checkbox.patch' = @{ MarkerFile = 'MFAAvalonia\Views\Pages\TaskQueueView.axaml.cs'; Marker = 'UseChipTaskCheckBox' }
    'laa-limited-trade-chip-options.patch' = @{ MarkerFile = 'MFAAvalonia\Helper\TaskOptionGenerator.cs'; Marker = 'IsLimitedTradeChipTypeOption' }
    'laa-pretask-path-resolution.patch' = @{ MarkerFile = 'MFAAvalonia\Extensions\MaaFW\MaaProcessor.cs'; Marker = 'localPythonCandidates' }
    'laa-pretask-config-sync.patch' = @{ MarkerFile = 'MFAAvalonia\Extensions\MaaFW\MaaProcessor.cs'; Marker = 'MFA_INSTANCE_CONFIG_PATH' }
    'laa-stop-on-task-failure.patch' = @{ MarkerFile = 'MFAAvalonia\Extensions\MaaFW\MaaProcessor.cs'; Marker = 'ContinueOnError = false' }
    'laa-no-autostart.patch' = @{ MarkerFile = 'MFAAvalonia\Views\Windows\RootView.axaml.cs'; Marker = 'if \(!noAutoStart\)|suppressAutoStartOnce' }
    'laa-reset-task-confirmation.patch' = @{ MarkerFile = 'MFAAvalonia\ViewModels\Pages\TaskQueueViewModel.cs'; Marker = '当前操作会重置任务列表中所有已有设置' }
    'laa-simplified-settings.patch' = @{ MarkerFile = 'MFAAvalonia\Views\Pages\SettingsView.axaml'; Marker = 'LAA: simplified settings' }
    'laa-project-profiles-scheduler.patch' = @{ MarkerFile = 'MFAAvalonia\ViewModels\Other\SystemScheduledTaskManager.cs'; Marker = 'SystemScheduledTaskManager' }
    'laa-emulator-minimize-setting.patch' = @{ MarkerFile = 'MFAAvalonia\Configuration\ConfigurationKeys.cs'; Marker = 'MinimizeEmulatorAfterLaunch' }
    'laa-simplified-start-end-actions.patch' = @{ MarkerFile = 'MFAAvalonia\ViewModels\UsersControls\Settings\StartSettingsUserControlModel.cs'; Marker = 'NormalizeBeforeTask' }
    'laa-settings-runtime-fixes.patch' = @{ MarkerFile = 'MFAAvalonia\Extensions\GlobalStartManager.cs'; Marker = '未进入运行状态' }
    'laa-rebrand-mcc-text.patch' = @{ MarkerFile = 'MFAAvalonia\Assets\Localization\Strings.resx'; Marker = 'MCC 任务管理器' }
    'laa-rebrand-mcc-logo.patch' = @{ MarkerFile = 'ui_custom\MFAAvalonia\laa-rebrand-mcc-logo.applied'; Marker = 'MCC branding: logo.ico replaced' }
}

$patchesList = Join-Path $PSScriptRoot 'patches.list'
$patches = Get-Content -LiteralPath $patchesList |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith('#') } |
    ForEach-Object {
        $file = $_
        if (-not $patchMarkers.ContainsKey($file)) {
            throw "patches.list entry missing marker map in build.ps1: $file"
        }
        $spec = $patchMarkers[$file].Clone()
        $spec['File'] = $file
        $spec
    }

foreach ($patchSpec in $patches) {
    $patch = Join-Path $PSScriptRoot $patchSpec.File
    $code = Invoke-Native -FilePath $git -Arguments @('-C', $source, 'apply', '--ignore-space-change', '--check', $patch) -Quiet
    if ($code -eq 0) {
        Invoke-Native -FilePath $git -Arguments @('-C', $source, 'apply', '--ignore-space-change', $patch) -Quiet | Out-Null
    } else {
        $markerPath = Join-Path $source $patchSpec.MarkerFile
        if ((Test-Path -LiteralPath $markerPath) -and
            (Select-String -LiteralPath $markerPath -Pattern $patchSpec.Marker -Quiet)) {
            continue
        }
        $reverse = Invoke-Native -FilePath $git -Arguments @('-C', $source, 'apply', '--ignore-space-change', '--reverse', '--check', $patch) -Quiet
        if ($reverse -ne 0) {
            throw "MFAAvalonia source does not match patch: $patch"
        }
    }
}

$buildRoot = Join-Path $projectRoot '.tmp\mfa-build'
$env:DOTNET_CLI_HOME = Join-Path $projectRoot '.tmp\dotnet-home'
$env:NUGET_PACKAGES = Join-Path $buildRoot 'nuget'
$env:TEMP = Join-Path $buildRoot 'temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:DOTNET_CLI_HOME, $env:NUGET_PACKAGES, $env:TEMP | Out-Null

# dotnet 会把警告/进度写到 stderr；在 $ErrorActionPreference='Stop' 下同样会
# 抛 NativeCommandError 终止脚本，所以统一把输出并进管道流（保留可读输出）。
$restoreCode = Invoke-Native -FilePath $dotnet -Arguments @(
    'restore', (Join-Path $source 'MFAAvalonia.Desktop\MFAAvalonia.Desktop.csproj'), '-r', 'win-x64')
if ($restoreCode -ne 0) {
    throw "MFAAvalonia restore failed with exit code $restoreCode"
}
$buildCode = Invoke-Native -FilePath $dotnet -Arguments @(
    'build', (Join-Path $source 'MFAAvalonia.Desktop\MFAAvalonia.Desktop.csproj'),
    '-c', 'Release', '-r', 'win-x64', '--no-restore')
if ($buildCode -ne 0) {
    throw "MFAAvalonia build failed with exit code $buildCode"
}

$running = Get-Process -Name 'MFAAvalonia' -ErrorAction SilentlyContinue
if ($running) {
    throw 'Close LAA before installing the rebuilt UI core.'
}

$builtCore = Join-Path $source 'bin\AnyCPU\Release\MFAAvalonia.Core.dll'
$targetCore = Join-Path $projectRoot 'install\libs\MFAAvalonia.Core.dll'
if (-not (Test-Path -LiteralPath (Split-Path $targetCore -Parent))) {
    throw 'Build the local install package before installing the customized UI core.'
}
Copy-Item -LiteralPath $builtCore -Destination $targetCore -Force
Write-Output "Installed customized UI core: $targetCore"

# exe 内嵌图标单独替换：
# Windows 任务栏与资源管理器读的是宿主 exe 的图标资源，与 Core.dll 无关，
# 而 install 里的 exe 来自 dotnet publish（NetBeauty 打包过 libs 目录），
# 直接用 build 输出替换 exe 会丢打包结构，所以只改图标资源。
$iconFile = Join-Path $source 'MFAAvalonia\Assets\logo.ico'
$iconCode = Invoke-Native -FilePath $rcedit -Arguments @($hostExe, '--set-icon', $iconFile)
if ($iconCode -ne 0) {
    throw "rcedit 替换 exe 图标失败（退出码 $iconCode）"
}
Write-Output "Installed exe icon: $hostExe"
