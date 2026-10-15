# verify.ps1 — самопроверка приложения без браузера.
# Прогоняет витрину и игру в Streamlit AppTest и печатает список проверок.
#
#   .\verify.ps1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Find-Python {
    $candidates = @()
    if ($env:DSH_PYTHON) { $candidates += $env:DSH_PYTHON }
    $candidates += (Join-Path $root ".venv\Scripts\python.exe")
    $candidates += "C:\Users\teacher\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $onPath3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($onPath3) { return $onPath3.Source }
    throw "Python не найден. Установите Python 3.10+ или укажите путь в переменной окружения DSH_PYTHON."
}

$python = Find-Python
$env:PYTHONPATH = Join-Path $root ".pylibs"
$env:PYTHONUTF8 = "1"
$env:TEMP = Join-Path $root ".testtmp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

& $python -X utf8 (Join-Path $root "test_app.py")
$appResult = $LASTEXITCODE

# Если сервер уже запущен, дополнительно проверяем ссылку через живой запрос.
$busy = & $python -X utf8 -c "import socket; s=socket.socket(); s.settimeout(0.6); print('busy' if s.connect_ex(('127.0.0.1', 8501))==0 else 'free'); s.close()"
if ($busy -eq "busy") {
    Write-Host ""
    & $python -X utf8 (Join-Path $root "probe_url.py") 8501
    if ($LASTEXITCODE -ne 0) { $appResult = 1 }
} else {
    Write-Host ""
    Write-Host "Сервер не запущен: проверка ссылки через живой запрос пропущена (.\start-detached.ps1)." -ForegroundColor DarkGray
}

exit $appResult
