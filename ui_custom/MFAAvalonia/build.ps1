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
    @{ File = 'laa-pretask-path-resolution.patch'; MarkerFile = 'MFAAvalonia\Extensions\MaaFW\MaaProcessor.cs'; Marker = 'localPythonCandidates' },
    @{ File = 'laa-stop-on-task-failure.patch'; MarkerFile = 'MFAAvalonia\Extensions\MaaFW\MaaProcessor.cs'; Marker = 'ContinueOnError = false' },
    @{ File = 'laa-no-autostart.patch'; MarkerFile = 'MFAAvalonia\Views\Windows\RootView.axaml.cs'; Marker = 'if \(!noAutoStart\)' },
    @{ File = 'laa-reset-task-confirmation.patch'; MarkerFile = 'MFAAvalonia\ViewModels\Pages\TaskQueueViewModel.cs'; Marker = '当前操作会重置任务列表中所有已有设置' }
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
& $dotnet build (Join-Path $source 'MFAAvalonia.Desktop\MFAAvalonia.Desktop.csproj') -c Release -r win-x64 --no-restore

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
