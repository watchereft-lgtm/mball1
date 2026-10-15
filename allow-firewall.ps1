# allow-firewall.ps1 — разрешить телефонам в той же Wi-Fi открывать игру.
#
# Запускать ОДИН РАЗ от имени администратора (правый клик по PowerShell -> «Запуск от имени администратора»):
#
#   .\allow-firewall.ps1                разрешить порт 8501 только своей подсети
#   .\allow-firewall.ps1 -Port 8600     другой порт
#   .\allow-firewall.ps1 -AnyRemote     разрешить с любых адресов (нужно, если телефон в другой сети)
#   .\allow-firewall.ps1 -Remove        удалить правило
#
# Без этого правила страница на телефоне не откроется: соединение режет брандмауэр Windows.
[CmdletBinding()]
param(
    [int]$Port = 8501,
    [switch]$AnyRemote,
    [switch]$Remove
)

$ruleName = "Магический шар (Streamlit) $Port"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Нужны права администратора. Откройте PowerShell от имени администратора и повторите." -ForegroundColor Yellow
    exit 1
}

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Remove-NetFirewallRule -DisplayName $ruleName
    Write-Host "Старое правило удалено, создаю заново." -ForegroundColor DarkGray
}

if ($Remove) {
    Write-Host "Правило «$ruleName» удалено." -ForegroundColor Green
    exit 0
}

$localAddress = ""
if (-not $AnyRemote) {
    try {
        $lanIp = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and
                $_.InterfaceAlias -notlike "*Loopback*" -and $_.InterfaceAlias -notlike "*Bluetooth*" -and
                $_.InterfaceAlias -notlike "*vEthernet*" -and $_.InterfaceAlias -notlike "*Virtual*"
            } | Sort-Object SkipAsSource, InterfaceMetric | Select-Object -First 1
        if ($lanIp) { $localAddress = "$($lanIp.IPAddress)/$($lanIp.PrefixLength)" }
    } catch {
        Write-Host "Не удалось определить свою подсеть, открываю порт для любых адресов." -ForegroundColor DarkYellow
    }
}

$params = @{
    DisplayName = $ruleName
    Description = "Разрешает телефонам открывать игру «Магический шар» на этом компьютере."
    Direction   = "Inbound"
    Action      = "Allow"
    Protocol    = "TCP"
    LocalPort   = $Port
    Profile     = "Private"
    Enabled     = "True"
}
if ($localAddress) { $params["RemoteAddress"] = $localAddress }

New-NetFirewallRule @params | Out-Null

if ($localAddress) {
    Write-Host "Готово: порт $Port открыт только для $localAddress" -ForegroundColor Green
} else {
    Write-Host "Готово: порт $Port открыт для любых адресов." -ForegroundColor Green
}
Write-Host "Проверьте, что сеть помечена как «Частная», иначе правило не сработает." -ForegroundColor DarkGray
Write-Host "Удалить правило: .\allow-firewall.ps1 -Port $Port -Remove" -ForegroundColor DarkGray
