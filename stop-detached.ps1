# stop-detached.ps1 — остановить сервер, запущенный через start-detached.ps1.
#
#   .\stop-detached.ps1
[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$pidFile = Join-Path $root "server.pid"

$stopped = @()

if (Test-Path $pidFile) {
    $serverPid = (Get-Content $pidFile -Raw).Trim()
    if ($serverPid -match '^\d+$') {
        foreach ($child in (Get-CimInstance Win32_Process -Filter "ParentProcessId = $serverPid" -ErrorAction SilentlyContinue)) {
            Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
            $stopped += $child.ProcessId
        }
        Stop-Process -Id ([int]$serverPid) -Force -ErrorAction SilentlyContinue
        $stopped += [int]$serverPid
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# Подчищаем всё, что осталось слушать порт 8501 или 8600.
foreach ($port in 8501, 8600) {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        $stopped += $listener.OwningProcess
    }
}

if ($stopped) {
    Write-Host "Остановлены процессы: $($stopped -join ', ')" -ForegroundColor Green
} else {
    Write-Host "Ничего не найдено — сервер уже остановлен." -ForegroundColor DarkGray
}
