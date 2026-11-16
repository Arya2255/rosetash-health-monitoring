param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [ValidateSet('desktop', 'web')][string]$Mode = 'desktop'
)
$ErrorActionPreference = 'Stop'

# Copy ONLY the EXE away from the checkout, interpreter and Flet build cache.
$sourceExe = (Resolve-Path -LiteralPath $ExePath).Path
$smokeRoot = Join-Path $env:RUNNER_TEMP ('roztash-onefile-' + [guid]::NewGuid())
$profileDir = Join-Path $smokeRoot 'profile'
$launchDir = Join-Path $smokeRoot 'launch'
$tempDir = Join-Path $smokeRoot 'temp'
New-Item -ItemType Directory -Force -Path $profileDir, $launchDir, $tempDir | Out-Null
$exe = Join-Path $launchDir 'RosetashHealthMonitoring.exe'
Copy-Item -LiteralPath $sourceExe -Destination $exe

# This script runs in its own CI step. Remove inherited developer settings,
# credentials, sessions and Python search paths; do not modify the runner account.
Get-ChildItem Env: | Where-Object {
    $_.Name -match '^(ROZTASH_|ROSETASH_|FLET_|PYTHONPATH$|PYTHONHOME$)'
} | ForEach-Object { Remove-Item ('Env:' + $_.Name) }
$env:HOME = $profileDir
$env:USERPROFILE = $profileDir
$env:APPDATA = Join-Path $profileDir 'AppData/Roaming'
$env:LOCALAPPDATA = Join-Path $profileDir 'AppData/Local'
$env:TEMP = $tempDir
$env:TMP = $tempDir
$env:ROZTASH_CF_HOME = Join-Path $profileDir '.cloudflared'
$env:ROZTASH_LOG_DIR = Join-Path $smokeRoot 'logs'
$env:ROZTASH_HOME = Join-Path $profileDir 'Roztash'
$env:ROZTASH_VIEW = 'login'
$env:ROZTASH_LIVE = 'off'
# Fail immediately if the packed client attempts a first-run download.
$env:FLET_CLIENT_URL = 'http://127.0.0.1:1/must-use-bundled-client'
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
New-Item -ItemType Directory -Force -Path $env:APPDATA, $env:LOCALAPPDATA | Out-Null
$stdout = Join-Path $smokeRoot 'stdout.txt'
$stderr = Join-Path $smokeRoot 'stderr.txt'
$process = $null
$client = $null
$webReady = $false
if ($Mode -eq 'web') {
    if (Get-NetTCPConnection -LocalPort 8550 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Port 8550 was already occupied before the smoke test'
    }
    $env:FLET_FORCE_WEB_SERVER = 'true'
    $env:FLET_SERVER_IP = '127.0.0.1'
    $env:FLET_SERVER_PORT = '8550'
}

try {
    $launchOptions = @{
        FilePath = $exe; WorkingDirectory = $launchDir; PassThru = $true
        RedirectStandardOutput = $stdout; RedirectStandardError = $stderr
    }
    if ($Mode -eq 'web') { $launchOptions.ArgumentList = @('--web') }
    $process = Start-Process @launchOptions
    $deadline = [DateTime]::UtcNow.AddSeconds(75)
    while ([DateTime]::UtcNow -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) { throw "EXE exited during startup: $($process.ExitCode)" }
        if ($Mode -eq 'web') {
            try {
                $response = Invoke-WebRequest 'http://127.0.0.1:8550/' -TimeoutSec 2
                $webReady = $response.StatusCode -eq 200
            } catch { $webReady = $false }
            if ($webReady) { break }
            Start-Sleep -Seconds 1
            continue
        }
        $client = Get-Process -Name flet -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and $_.Path.StartsWith($profileDir, [StringComparison]::OrdinalIgnoreCase) `
                -and $_.MainWindowHandle -ne 0 `
                -and $_.MainWindowTitle -eq 'پایش سلامت کارکنان — رزتاش'
        } | Select-Object -First 1
        if ($client) { break }
        Start-Sleep -Seconds 1
    }
    if ($Mode -eq 'web') {
        if (-not $webReady) { throw 'Web server did not answer HTTP 200 on 127.0.0.1:8550' }
        if ($response.Content -notmatch 'flet.noCdn=true') { throw 'Web entrypoint did not disable CDN dependencies' }
        foreach ($path in @('flutter_bootstrap.js', 'main.dart.js', 'canvaskit/canvaskit.wasm',
                             'assets/FontManifest.json', 'logo-colored.png', 'fonts/Vazirmatn-Regular.ttf')) {
            $asset = Invoke-WebRequest "http://127.0.0.1:8550/$path" -TimeoutSec 15
            if ($asset.StatusCode -ne 200 -or $asset.RawContentLength -eq 0) {
                throw "Embedded web asset did not load: $path"
            }
        }
        $socket = [System.Net.WebSockets.ClientWebSocket]::new()
        $cancel = [System.Threading.CancellationTokenSource]::new(10000)
        try {
            $socket.ConnectAsync([uri]'ws://127.0.0.1:8550/ws', $cancel.Token).GetAwaiter().GetResult()
            if ($socket.State -ne [System.Net.WebSockets.WebSocketState]::Open) {
                throw 'Flet WebSocket did not open'
            }
        } finally { $socket.Abort(); $socket.Dispose(); $cancel.Dispose() }
    } else {
        if (-not $client) { throw 'No app-titled Flet window appeared from the isolated profile' }
        $client.Refresh()
        if ($client.HasExited -or -not $client.Responding) {
            throw 'Desktop client exited or became unresponsive'
        }
    }
    # A bootloader or error dialog alone is not a pass: require the Flet window
    # Both launch modes must bootstrap the actual local data bridge and broker.
    $health = Invoke-RestMethod 'http://127.0.0.1:8726/health' -TimeoutSec 5
    if (-not $health.ok) { throw 'Bundled data bridge is not healthy' }
    if (-not ([IO.Path]::GetFullPath($health.db)).StartsWith($env:ROZTASH_HOME, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Database is not in the persistent Windows profile'
    }
    $runtime = Get-ChildItem (Join-Path $env:ROZTASH_HOME 'runtime') -Directory | Select-Object -First 1
    $publisher = Join-Path $runtime.FullName 'mosquitto/mosquitto_pub.exe'
    & $publisher -h 127.0.0.1 -p 1884 -t 'roztash/ci-gateway/status' -m '{"zone":"CI","fw":"synthetic-ci","ip":"127.0.0.1","uptime_s":10}'
    if ($LASTEXITCODE -ne 0) { throw 'Bundled MQTT publisher could not publish' }
    $ingested = $false
    for ($i = 0; $i -lt 20; $i++) {
        $snap = Invoke-RestMethod 'http://127.0.0.1:8726/api/snapshot' -TimeoutSec 3
        if ($snap.gateways | Where-Object { $_.gw -eq 'ci-gateway' }) { $ingested = $true; break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ingested) { throw 'MQTT message did not reach the bundled SQLite bridge' }
    $udp = [System.Net.Sockets.UdpClient]::new()
    try {
        $udp.Client.ReceiveTimeout = 5000
        $query = [Text.Encoding]::ASCII.GetBytes('ROZTASH_DISCOVERYWHERE_ARE_YOU')
        $udp.Send($query, $query.Length, '127.0.0.1', 19198) | Out-Null
        $peer = [System.Net.IPEndPoint]::new([System.Net.IPAddress]::Any, 0)
        $answer = [Text.Encoding]::UTF8.GetString($udp.Receive([ref]$peer))
        if (-not $answer.StartsWith('ROZTASH_DISCOVERYHERE_I_AM')) { throw 'Discovery response missing' }
        $details = $answer.Substring('ROZTASH_DISCOVERYHERE_I_AM'.Length) | ConvertFrom-Json
        if ($details.mqtt_port -ne 1884 -or $details.mqtt_host -ne '127.0.0.1') { throw 'Invalid discovery address' }
    } finally { $udp.Dispose() }
    $web = Invoke-WebRequest 'http://127.0.0.1:8550/' -TimeoutSec 5
    if ($web.StatusCode -ne 200) { throw 'Web did not auto-start alongside desktop' }
    $cloudflared = Join-Path $runtime.FullName 'cloudflared.exe'
    & $cloudflared --version
    if ($LASTEXITCODE -ne 0) { throw 'Bundled tunnel binary does not execute' }
    Write-Host 'PASS: bundled MQTT -> SQLite/HTTP, UDP discovery, automatic web and cloudflared binary'
    # or web server and the Python process to remain alive through settling.
    Start-Sleep -Seconds 10
    $process.Refresh()
    if ($process.HasExited) { throw 'Application process exited during settling interval' }
    if ($Mode -eq 'web') {
        try {
            $response = Invoke-WebRequest 'http://127.0.0.1:8550/' -TimeoutSec 2
            if ($response.StatusCode -ne 200 -or $response.Content -notmatch 'flet') {
                throw 'Web server stopped serving the Flet index'
            }
        } catch { throw "Web server failed during settling interval: $_" }
    } else {
        $client.Refresh()
        if ($client.HasExited -or -not $client.Responding) {
            throw 'Desktop client exited or became unresponsive'
        }
    }
    $diagnosticFiles = @(Get-Item $stdout, $stderr -ErrorAction SilentlyContinue)
    $diagnosticFiles += @(Get-ChildItem $env:ROZTASH_LOG_DIR -Filter '*.log' -ErrorAction SilentlyContinue)
    $errors = $diagnosticFiles | Select-String -Pattern `
        'Traceback|ModuleNotFoundError|ImportError|Failed to execute script|\|\s*(ERROR|CRITICAL)\s*\|'
    if ($errors) { throw ($errors | Out-String) }
    if (Test-Path (Join-Path $env:ROZTASH_HOME 'session.json')) {
        throw 'Smoke launch unexpectedly created a login session'
    }
    Write-Host "PASS: standalone windowed EXE $Mode smoke with an empty profile, embedded Flet runtime, and no Python on PATH; alive after 10 seconds."
    Write-Host 'Launch smoke only: no login, mail, hardware flashing or Cloudflare credentials were used.'
} finally {
    foreach ($file in @($stdout, $stderr)) {
        if (Test-Path $file) { Get-Content -LiteralPath $file }
    }
    if ($process -and -not $process.HasExited) {
        & "$env:SystemRoot\System32\taskkill.exe" /PID $process.Id /T /F | Out-Null
    }
    if ($client -and -not $client.HasExited) {
        Stop-Process -Id $client.Id -Force -ErrorAction SilentlyContinue
    }
    # taskkill's return code must not overwrite a successful smoke result.
    $global:LASTEXITCODE = 0
}
