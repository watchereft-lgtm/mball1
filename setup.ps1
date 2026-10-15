# setup.ps1 — один раз скачать зависимости в .pylibs.
#
#   .\setup.ps1              скачать то, чего не хватает
#   .\setup.ps1 -Clean       удалить .pylibs и скачать заново (лечит битую установку)
#
# pip здесь не используется: он не умеет писать в свои временные папки при
# ограниченных правах, поэтому колёса качает и распаковывает setup_deps.py.
[CmdletBinding()]
param(
    [switch]$Clean
)

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
Write-Host "Python: $python" -ForegroundColor DarkGray
$env:PYTHONUTF8 = "1"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$arguments = @((Join-Path $root "setup_deps.py"))
if ($Clean) { $arguments += "--clean" }

& $python -X utf8 @arguments
exit $LASTEXITCODE
