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

if (-not (Test-Path $settingsPath)) {
    throw "launcher_settings.json was not found in $root"
}

$settings = Get-Content $settingsPath -Raw | ConvertFrom-Json
$port = [int]$settings.port
$settings.host = "0.0.0.0"
$settings | ConvertTo-Json -Depth 5 | Set-Content $settingsPath -Encoding ASCII

Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

New-NetFirewallRule `
    -DisplayName $ruleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $port `
    -Profile Private `
    -RemoteAddress LocalSubnet | Out-Null

Write-Host ""
Write-Host "DreiTrack private LAN access is enabled." -ForegroundColor Green
Write-Host ""
Write-Host "Firewall rule: $ruleName"
Write-Host "TCP port: $port"
Write-Host "Allowed Windows network profile: Private"
Write-Host "Allowed remote scope: LocalSubnet"
Write-Host ""

$activePrivate = Get-NetConnectionProfile -ErrorAction SilentlyContinue |
    Where-Object { $_.NetworkCategory -eq "Private" }

if (-not $activePrivate) {
    Write-Warning "Windows does not currently show an active Private network profile."
    Write-Warning "The firewall rule will not accept LAN connections until the company network is classified as Private."
}

$hostname = $env:COMPUTERNAME
Write-Host "Employees can first try: http://${hostname}:$port"

$addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -ne "127.0.0.1" -and
        $_.IPAddress -notlike "169.254.*" -and
        $_.AddressState -eq "Preferred"
    } |
    Select-Object -ExpandProperty IPAddress -Unique

foreach ($address in $addresses) {
    Write-Host "Private IPv4 fallback: http://${address}:$port"
}

Write-Host ""
Write-Host "DreiTrack was stopped if it was running. Start it again with DreiTrack.vbs."
Write-Host "Do NOT create an internet router port-forward for this port." -ForegroundColor Yellow
Write-Host ""
Read-Host "Press Enter to close"
