$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$settingsPath = Join-Path $root "launcher_settings.json"
$ruleName = "DreiTrack Private LAN"
$serverPidPath = Join-Path $root "logs\dreitrack-server.pid"

if (Test-Path $serverPidPath) {
    try {
        $serverPid = [int](Get-Content $serverPidPath -Raw).Trim()
        Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue
    } catch {
        # A stale PID file should not block changing network mode.
    }
    Remove-Item $serverPidPath -Force -ErrorAction SilentlyContinue
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$adminRole = [Security.Principal.WindowsBuiltInRole]::Administrator

if (-not $principal.IsInRole($adminRole)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`""
    )
    exit
}

if (Test-Path $settingsPath) {
    $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
    $settings.host = "127.0.0.1"
    $settings | ConvertTo-Json -Depth 5 | Set-Content $settingsPath -Encoding ASCII
}

Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "DreiTrack private LAN access is disabled." -ForegroundColor Green
Write-Host "The launcher is back to 127.0.0.1 (this computer only)."
Write-Host ""
Write-Host "DreiTrack was stopped if it was running. Start it again with DreiTrack.vbs."
Write-Host ""
Read-Host "Press Enter to close"
