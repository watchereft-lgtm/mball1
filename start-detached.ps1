# start-detached.ps1 — запустить сервер отдельным процессом, не привязанным к этой сессии.
#
#   .\start-detached.ps1            запуск на порту 8501
#   .\start-detached.ps1 -Port 8600 другой порт
#
# Лог пишется в server.log рядом с этим файлом, номер процесса — в server.pid.
# Остановить: .\stop-detached.ps1
[CmdletBinding()]
param(
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$log = Join-Path $root "server.log"
$pidFile = Join-Path $root "server.pid"

$existing = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Порт $Port уже слушается (PID $($existing[0].OwningProcess))." -ForegroundColor Yellow
    exit 1
}

$command = "cmd.exe /c `"powershell -NoProfile -ExecutionPolicy Bypass -File `"`"$root\run.ps1`"`" -Port $Port > `"`"$log`"`" 2>&1`""
$process = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $command }
if ($process.ReturnValue -ne 0) {
    throw "Не удалось создать процесс: код $($process.ReturnValue)"
}

Set-Content -Path $pidFile -Value $process.ProcessId -Encoding ascii
Write-Host "Запущено, PID $($process.ProcessId), лог: $log" -ForegroundColor Green
Write-Host "Остановить: .\stop-detached.ps1" -ForegroundColor DarkGray
