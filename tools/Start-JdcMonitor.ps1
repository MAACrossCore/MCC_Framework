param([double]$Interval = 1.0)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$out = Join-Path $root ('debug\jdc-monitor\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$python = Join-Path $root '.venv\Scripts\python.exe'
if (!(Test-Path $python)) { $python = Join-Path $root 'install\python\python.exe' }
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = Join-Path $root '.tmp'
$env:TMP = $env:TEMP
$process = Start-Process -FilePath $python -ArgumentList @('-B', "`"$PSScriptRoot\monitor_jdc.py`"", '--out', "`"$out`"", '--interval', $Interval) -WorkingDirectory $root -WindowStyle Hidden -PassThru
Write-Output "Monitor PID: $($process.Id)"
Write-Output "Output: $out"
