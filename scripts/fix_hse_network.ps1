# ==============================================================================
# Roztash HSE Network Fix — Windows PowerShell Script
# ==============================================================================
# این اسکریپت کارت Ethernet ویندوز را به آی‌پی ثابت تنظیم می‌کند
# و اتصال به ESP32 را تایید می‌کند.
#
# دو دکمه دارد: تنظیم آی‌پی و تست اتصال.
# ==============================================================================

# --- تنظیمات شبکه (باید با فریم‌ور ESP32 یکی باشد) ---
$ESP32_STATIC_IP   = "192.168.50.100"
$WINDOWS_STATIC_IP = "192.168.50.10"
$SUBNET_MASK       = "255.255.255.0"
$GATEWAY           = "192.168.50.1"
$DNS               = "8.8.8.8"

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "  Roztash HSE — تنظیم شبکه سوئیچ (Windows)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# --- پیدا کردن کارت Ethernet ---
Write-Host "`n[۱] جستجوی کارت Ethernet..." -ForegroundColor Yellow
$ethAdapters = Get-NetAdapter | Where-Object {
    $_.InterfaceDescription -match "Ethernet|Intel.*I219|Realtek|Broadcom" -and
    $_.Status -eq "Up"
}

if ($ethAdapters.Count -eq 0) {
    Write-Host "  ✗ کارت Ethernet فعال پیدا نشد." -ForegroundColor Red
    Write-Host "  لطفاً کابل Ethernet را وصل کنید و دوباره اجرا کنید." -ForegroundColor Red
    exit 1
}

Write-Host "  کارت‌های یافت شده:" -ForegroundColor Green
$ethAdapters | ForEach-Object {
    Write-Host "    - $($_.Name) : $($_.InterfaceDescription)" -ForegroundColor Green
}

$ethName = $ethAdapters[0].Name
Write-Host "`n  استفاده از: $ethName" -ForegroundColor Cyan

# --- تنظیم آی‌پی ثابت ---
Write-Host "`n[۲] تنظیم آی‌پی ثابت $WINDOWS_STATIC_IP..." -ForegroundColor Yellow

try {
    New-NetIPAddress -InterfaceAlias $ethName -IPAddress $WINDOWS_STATIC_IP `
        -PrefixLength 24 -DefaultGateway $GATEWAY -ErrorAction Stop | Out-Null
    Write-Host "  ✓ آی‌پی تنظیم شد." -ForegroundColor Green
} catch {
    Write-Host "  ✗ خطا در تنظیم آی‌پی: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# تنظیم DNS
try {
    Set-DnsClientServerAddress -InterfaceAlias $ethName -ServerAddresses $DNS -ErrorAction Stop | Out-Null
    Write-Host "  ✓ DNS تنظیم شد." -ForegroundColor Green
} catch {
    Write-Host "  ⚠ DNS تنظیم نشد (بدون daño ادامه می‌یابد)." -ForegroundColor Yellow
}

# --- تایید تنظیمات ---
Write-Host "`n[۳] تایید تنظیمات شبکه..." -ForegroundColor Yellow
$ipCfg = Get-NetIPAddress -InterfaceAlias $ethName -AddressFamily IPv4 | Select-Object IPAddress, PrefixLength
Write-Host "  آی‌پی: $($ipCfg.IPAddress)" -ForegroundColor Green
Write-Host "  ماسک: /$($ipCfg.PrefixLength)" -ForegroundColor Green

# --- تست اتصال به ESP32 ---
Write-Host "`n[۴] تست اتصال به ESP32 ($ESP32_STATIC_IP)..." -ForegroundColor Yellow

Write-Host "  پینگ..." -NoNewline
$pingResult = Test-Connection -ComputerName $ESP32_STATIC_IP -Count 3 -Quiet -ErrorAction SilentlyContinue
if ($pingResult) {
    Write-Host " ✓ پاسخ دریافت شد." -ForegroundColor Green
} else {
    Write-Host " ✗ پاسخ دریافت نشد." -ForegroundColor Red
    Write-Host "  لطفاً بررسی کنید:" -ForegroundColor Yellow
    Write-Host "    1. ESP32 روی سوئیچ که ویندوز هم روی آن است، وصل است؟" -ForegroundColor Yellow
    Write-Host "    2. آی‌پی ESP32 واقعی $ESP32_STATIC_IP است؟" -ForegroundColor Yellow
    Write-Host "    3. سوئیچ‌های دوگانه به هم وصل هستند؟" -ForegroundColor Yellow
}

# --- تست پورت discovery و bridge ---
Write-Host "`n[۵] تست پورت‌های Hermes..." -ForegroundColor Yellow
$ports = @(1884, 8726)
foreach ($port in $ports) {
    Write-Host "  پورت $port..." -NoNewline
    try {
        $socket = New-Object System.Net.Sockets.TcpClient
        $result = $socket.BeginConnect($ESP32_STATIC_IP, $port, $null, $null)
        $success = $result.AsyncWaitHandle.WaitOne(2000, $false)
        if ($success) {
            $socket.EndConnect($result)
            $socket.Close()
            Write-Host " ✓ باز است." -ForegroundColor Green
        } else {
            Write-Host " ✗ بسته است." -ForegroundColor Red
        }
    } catch {
        Write-Host " ✗ خطا: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# --- جمع‌بندی ---
Write-Host "`n============================================================" -ForegroundColor Cyan
if (Test-Connection -ComputerName $ESP32_STATIC_IP -Count 1 -Quiet -ErrorAction SilentlyContinue) {
    Write-Host "  ✅ شبکه سوئیچ آماده است. ESP32 در دسترس است." -ForegroundColor Green
    Write-Host "    هرMes می‌تواند با ESP32 ارتباط برقرار کند." -ForegroundColor Green
} else {
    Write-Host "  ⚠ شبکه هنوز آماده نیست. لطفاً موارد بالا را بررسی کنید." -ForegroundColor Yellow
}
Write-Host "============================================================`n" -ForegroundColor Cyan