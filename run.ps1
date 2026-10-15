# run.ps1 — запуск «Магического шара предсказаний» на этом компьютере.
#
#   .\run.ps1                 запуск на порту 8501
#   .\run.ps1 -Port 8600      другой порт
#   .\run.ps1 -Ip 192.168.1.5 вручную указать адрес для QR-кода
#
# Зависимости берутся из .pylibs рядом с этим файлом, глобально ничего не ставится.
# Если .pylibs ещё нет — сначала выполните .\setup.ps1
[CmdletBinding()]
param(
    [int]$Port = 8501,
    [string]$Ip = ""
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# --- Python: комплектный интерпретатор DSH, виртуальное окружение, затем PATH ---
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
$libs = Join-Path $root ".pylibs"
if (-not (Test-Path $libs)) {
    throw "Папка .pylibs не найдена. Выполните один раз .\setup.ps1 — он скачает зависимости."
}
$app = Join-Path $root "app.py"
if (-not (Test-Path $app)) { throw "Не найден app.py рядом с run.ps1." }

$env:PYTHONPATH = $libs
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
# Русский текст должен читаться и когда вывод перенаправлен в файл (например, server.log).
try { $OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }

# --- Помощник: спросить Python то, что надёжнее спросить у него ---
function Invoke-PythonHelper {
    param([string]$Code)
    try {
        $result = & $python -X utf8 -c $Code 2>$null
        if ($LASTEXITCODE -eq 0 -and $result) { return ($result | Select-Object -First 1).ToString().Trim() }
    } catch { }
    return ""
}

# --- Локальный IPv4 для ссылки в QR-коде ---
function Get-LanIp {
    $usable = {
        param($address)
        $address.IPAddress -notlike "127.*" -and
        $address.IPAddress -notlike "169.254.*" -and
        $address.PrefixOrigin -ne "WellKnown" -and
        $address.InterfaceAlias -notlike "*Loopback*" -and
        $address.InterfaceAlias -notlike "*Bluetooth*" -and
        $address.InterfaceAlias -notlike "*vEthernet*" -and
        $address.InterfaceAlias -notlike "*Virtual*"
    }

    # 1) реальные адреса адаптеров; Wi-Fi и Ethernet важнее всего остального
    try {
        $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object $usable)
        $preferred = $addresses | Where-Object {
            $_.InterfaceAlias -like "*Беспроводная*" -or $_.InterfaceAlias -like "*Wi-Fi*" -or $_.InterfaceAlias -like "*Wireless*"
        }
        $chosen = ($preferred + $addresses) | Sort-Object SkipAsSource, InterfaceMetric | Select-Object -First 1
        if ($chosen) { return $chosen.IPAddress }
    } catch { }

    # 2) адрес интерфейса, через который машина выходит в сеть
    $viaRoute = Invoke-PythonHelper @"
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('8.8.8.8', 80))
    print(s.getsockname()[0])
except OSError:
    pass
finally:
    s.close()
"@
    if ($viaRoute -and $viaRoute -notlike "127.*" -and $viaRoute -notlike "169.254.*") { return $viaRoute }

    # 3) последний шанс — разбор вывода ipconfig
    $match = ipconfig | Select-String -Pattern "IPv4[^:]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)"
    foreach ($found in $match) {
        $candidate = $found.Matches[0].Groups[1].Value
        if ($candidate -notlike "127.*" -and $candidate -notlike "169.254.*") { return $candidate }
    }
    return ""
}

# --- Порт: если занят, честно об этом сказать ---
function Test-PortBusy {
    $pythonVerdict = Invoke-PythonHelper @"
import socket, sys
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.6)
busy = s.connect_ex(('127.0.0.1', $Port)) == 0
s.close()
print('busy' if busy else 'free')
"@
    if ($pythonVerdict) { return ($pythonVerdict -eq "busy") }
    try {
        $busy = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop
        return [bool]$busy
    } catch { return $false }
}

$lanIp = $Ip
if (-not $lanIp) { $lanIp = Get-LanIp }

if (Test-PortBusy) {
    Write-Host "Порт $Port уже занят." -ForegroundColor Yellow
    Write-Host "Запустите с другим портом:  .\run.ps1 -Port 8600" -ForegroundColor Yellow
    exit 1
}

# Сообщаем приложению, какой порт и адрес реально используются: страница должна
# показать тот же адрес, что напечатан здесь, даже если у машины несколько сетей.
Set-Content -Path (Join-Path $root ".port") -Value $Port -Encoding ascii
Set-Content -Path (Join-Path $root ".ip") -Value $lanIp -Encoding ascii

$link = if ($lanIp) { "http://${lanIp}:${Port}/?screen=game" } else { "http://127.0.0.1:${Port}/?screen=game" }

Write-Host ""
Write-Host "  Магический шар предсказаний" -ForegroundColor Magenta
Write-Host "  Витрина с QR-кодом : http://127.0.0.1:$Port/"
Write-Host "  Игра для телефона  : $link" -ForegroundColor Green
if (-not $lanIp) {
    Write-Host "  Внимание: локальный IPv4 не найден, в QR-код попадёт 127.0.0.1 — телефон такую ссылку не откроет." -ForegroundColor Yellow
    Write-Host "  Подключитесь к Wi-Fi или укажите адрес вручную: .\run.ps1 -Ip 192.168.0.10" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  Остановить сервер: Ctrl+C" -ForegroundColor DarkGray
Write-Host ""

$arguments = @(
    "-m", "streamlit", "run", $app,
    "--global.developmentMode", "false",
    "--server.address", "0.0.0.0",
    "--server.port", "$Port",
    "--server.headless", "true",
    "--browser.gatherUsageStats", "false",
    "--client.showErrorDetails", "full",
    "--theme.base", "light"
)

& $python @arguments
