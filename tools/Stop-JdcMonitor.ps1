param([string]$Session)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
if (!$Session) {
    $Session = (Get-ChildItem (Join-Path $root 'debug\jdc-monitor') -Directory | Sort-Object Name -Descending | Select-Object -First 1).FullName
}
if (!$Session -or !(Test-Path (Join-Path $Session 'session.json'))) { throw 'Monitor session not found' }
New-Item -ItemType File -Path (Join-Path $Session 'STOP') -Force | Out-Null
Write-Output "Stopping monitor: $Session (does not stop MCC)"
