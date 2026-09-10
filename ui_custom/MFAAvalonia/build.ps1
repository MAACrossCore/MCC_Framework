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
$patches = @(
    @{ File = 'laa-chip-filter.patch'; MarkerFile = 'MFAAvalonia\Features\ChipFilter\ChipFilterPlan.cs'; Marker = 'ChipFilterCatalog' },
    @{ File = 'laa-chip-filter-total-level.patch'; MarkerFile = 'MFAAvalonia\Features\ChipFilter\ChipFilterPlan.cs'; Marker = 'MinimumTotalLevel' },
    @{ File = 'laa-chip-task-checkbox.patch'; MarkerFile = 'MFAAvalonia\Helper\TaskOptionGenerator.cs'; Marker = 'UseChipTaskCheckBox' },
    @{ File = 'laa-daily-chip-stage-schedule.patch'; MarkerFile = 'MFAAvalonia\Helper\TaskOptionGenerator.cs'; Marker = 'DailyChipStageSchedule' },
    @{ File = 'laa-limited-trade-chip-options.patch'; MarkerFile = 'MFAAvalonia\Helper\TaskOptionGenerator.cs'; Marker = 'IsLimitedTradeChipTypeOption' },
    @{ File = 'laa-pretask-path-resolution.patch'; MarkerFile = 'MFAAvalonia\Extensions\MaaFW\MaaProcessor.cs'; Marker = 'localPythonCandidates' },
    @{ File = 'laa-pretask-config-sync.patch'; MarkerFile = 'MFAAvalonia\Extensions\MaaFW\MaaProcessor.cs'; Marker = 'MFA_INSTANCE_CONFIG_PATH' },
    @{ File = 'laa-stop-on-task-failure.patch'; MarkerFile = 'MFAAvalonia\Extensions\MaaFW\MaaProcessor.cs'; Marker = 'ContinueOnError = false' },
    @{ File = 'laa-no-autostart.patch'; MarkerFile = 'MFAAvalonia\Views\Windows\RootView.axaml.cs'; Marker = 'if \(!noAutoStart\)|suppressAutoStartOnce' },
    @{ File = 'laa-reset-task-confirmation.patch'; MarkerFile = 'MFAAvalonia\ViewModels\Pages\TaskQueueViewModel.cs'; Marker = '当前操作会重置任务列表中所有已有设置' },
    @{ File = 'laa-simplified-settings.patch'; MarkerFile = 'MFAAvalonia\Views\Pages\SettingsView.axaml'; Marker = 'LAA: simplified settings' },
    @{ File = 'laa-project-profiles-scheduler.patch'; MarkerFile = 'MFAAvalonia\ViewModels\Other\SystemScheduledTaskManager.cs'; Marker = 'SystemScheduledTaskManager' },
    @{ File = 'laa-emulator-minimize-setting.patch'; MarkerFile = 'MFAAvalonia\Configuration\ConfigurationKeys.cs'; Marker = 'MinimizeEmulatorAfterLaunch' },
    @{ File = 'laa-simplified-start-end-actions.patch'; MarkerFile = 'MFAAvalonia\ViewModels\UsersControls\Settings\StartSettingsUserControlModel.cs'; Marker = 'NormalizeBeforeTask' },
    @{ File = 'laa-settings-runtime-fixes.patch'; MarkerFile = 'MFAAvalonia\Extensions\GlobalStartManager.cs'; Marker = '未进入运行状态' }
)

foreach ($patchSpec in $patches) {
    $patch = Join-Path $PSScriptRoot $patchSpec.File
    & $git -C $source apply --check $patch 2>$null
    if ($LASTEXITCODE -eq 0) {
        & $git -C $source apply $patch
    } else {
        $markerPath = Join-Path $source $patchSpec.MarkerFile
        if ((Test-Path -LiteralPath $markerPath) -and
            (Select-String -LiteralPath $markerPath -Pattern $patchSpec.Marker -Quiet)) {
            continue
        }
        & $git -C $source apply --reverse --check $patch 2>$null
        if ($LASTEXITCODE -ne 0) {
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

& $dotnet restore (Join-Path $source 'MFAAvalonia.Desktop\MFAAvalonia.Desktop.csproj') -r win-x64
if ($LASTEXITCODE -ne 0) {
    throw "MFAAvalonia restore failed with exit code $LASTEXITCODE"
}
& $dotnet build (Join-Path $source 'MFAAvalonia.Desktop\MFAAvalonia.Desktop.csproj') -c Release -r win-x64 --no-restore
if ($LASTEXITCODE -ne 0) {
    throw "MFAAvalonia build failed with exit code $LASTEXITCODE"
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
