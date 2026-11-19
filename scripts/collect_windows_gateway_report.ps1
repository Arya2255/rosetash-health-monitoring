# Collect a local Roztash connectivity report. Run as the app's Windows user.
# The only network operations are local HTTP GETs, an MQTT status subscription,
# and, when supplied, one UDP discovery request to the specified gateway.
# No raw messages, credentials, staff identities, or vital readings are printed.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('\A[a-z0-9][a-z0-9._-]{0,22}\z', Options = [System.Text.RegularExpressions.RegexOptions]::None)]
    [string]$GatewayId,
    [ValidatePattern('\A(?:[0-9]{1,3}\.){3}[0-9]{1,3}\z')]
    [string]$GatewayIp,
    [ValidatePattern('\A(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\z')]
    [string]$BandMac,
    [ValidateRange(1, 65535)] [int]$MqttPort = 1884,
    [ValidateRange(1, 65535)] [int]$BridgePort = 8726,
    [ValidateRange(2, 90)] [int]$WaitSeconds = 70
)

$ErrorActionPreference = 'Stop'
if ($GatewayIp) {
    $address = $null
    if (-not [Net.IPAddress]::TryParse($GatewayIp, [ref]$address) -or
            $address.ToString() -ne $GatewayIp -or
            $address.GetAddressBytes()[0] -eq 0 -or
            $address.GetAddressBytes()[0] -ge 224) {
        throw 'Supply the exact unicast IPv4 address of the board, or omit GatewayIp.'
    }
}

function Get-GatewayDiscovery {
    if (-not $GatewayIp) { return @{ result = 'not_requested' } }
    $socket = [Net.Sockets.UdpClient]::new()
    try {
        $socket.Client.ReceiveTimeout = 2500
        $socket.Connect($address, 19199)
        $query = [Text.Encoding]::ASCII.GetBytes('ROZTASH_GATEWAY_DISCOVERYWHO_IS_THERE')
        [void]$socket.Send($query, $query.Length)
        $peer = [Net.IPEndPoint]::new([Net.IPAddress]::Any, 0)
        $packet = $socket.Receive([ref]$peer)
        $prefix = 'ROZTASH_GATEWAY_DISCOVERYGATEWAY_HERE'
        $text = [Text.Encoding]::UTF8.GetString($packet)
        if ($packet.Length -gt 512 -or -not $text.StartsWith($prefix, [StringComparison]::Ordinal)) {
            return @{ result = 'unexpected_reply' }
        }
        $reply = ConvertFrom-Json -InputObject $text.Substring($prefix.Length)
        if ($reply.v -ne 1 -or $reply.transport -cne 'ethernet' -or $reply.mqtt_connected -isnot [bool]) {
            return @{ result = 'unexpected_reply' }
        }
        if ($reply.gw -cne $GatewayId) { return @{ result = 'gateway_id_mismatch' } }
        return @{ result = 'reply_received'; board_reports_mqtt_connected = $reply.mqtt_connected }
    } catch {
        $cause = $_.Exception.GetBaseException()
        if ($cause -is [Net.Sockets.SocketException] -and $cause.SocketErrorCode -eq 'TimedOut') {
            return @{ result = 'no_reply_before_deadline' }
        }
        return @{ result = 'discovery_error'; error_type = $cause.GetType().Name }
    } finally {
        $socket.Dispose()
    }
}

function Get-BridgeSnapshot {
    $request = [Net.HttpWebRequest][Net.WebRequest]::Create("http://127.0.0.1:$BridgePort/api/snapshot")
    $request.Proxy = $null
    $request.AllowAutoRedirect = $false
    $request.Timeout = 4000
    $request.ReadWriteTimeout = 4000
    $response = $request.GetResponse()
    try {
        if ([int]$response.StatusCode -ne 200) { throw 'Unexpected bridge response' }
        $reader = [IO.StreamReader]::new($response.GetResponseStream(), [Text.Encoding]::UTF8)
        try { return (ConvertFrom-Json -InputObject $reader.ReadToEnd()) }
        finally { $reader.Dispose() }
    } finally {
        $response.Dispose()
    }
}

function Get-MqttStatus {
    # The portable EXE may launch Mosquitto from its temporary extraction directory.
    $clientName = if ($env:OS -eq 'Windows_NT') { 'mosquitto_sub.exe' } else { 'mosquitto_sub' }
    $subscriber = Get-Command $clientName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $clientPath = if ($subscriber) { $subscriber.Source }
    if (-not $clientPath) {
        foreach ($process in @(Get-Process -Name mosquitto_sub, mosquitto -ErrorAction SilentlyContinue)) {
            if ($process.Path) {
                $candidate = Join-Path (Split-Path -LiteralPath $process.Path) $clientName
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $clientPath = $candidate; break }
            }
        }
    }
    if (-not $clientPath) { return @{ result = 'subscriber_not_found' } }
    $child = [Diagnostics.Process]::new()
    try {
        $child.StartInfo.FileName = $clientPath
        $child.StartInfo.Arguments = "-h 127.0.0.1 -p $MqttPort -t roztash/$GatewayId/status -R -C 1 -W $WaitSeconds"
        $child.StartInfo.UseShellExecute = $false
        $child.StartInfo.CreateNoWindow = $true
        $child.StartInfo.RedirectStandardOutput = $true
        $child.StartInfo.RedirectStandardError = $true
        [void]$child.Start()
        $stdout = $child.StandardOutput.ReadToEndAsync()
        $stderr = $child.StandardError.ReadToEndAsync()
        if (-not $child.WaitForExit(($WaitSeconds + 3) * 1000)) {
            $child.Kill()
            return @{ result = 'subscriber_deadline' }
        }
        if ($child.ExitCode -ne 0) {
            $reason = if ($stderr.GetAwaiter().GetResult() -match 'timed out') { 'no_fresh_status_before_deadline' } else { 'subscription_failed' }
            return @{ result = $reason; exit_code = $child.ExitCode }
        }
        $status = ConvertFrom-Json -InputObject ($stdout.GetAwaiter().GetResult())
        if ($status.online -isnot [bool] -or ($status.online -and $status.gw -cne $GatewayId)) {
            return @{ result = 'unexpected_status' }
        }
        return @{ result = 'fresh_status_received'; online = $status.online;
                  scan_policy_ready = $status.scan_policy_ready -eq $true;
                  scan_enabled = $status.scan_enabled -eq $true;
                  manual_measurement_supported = $status.manual_measurement -eq $true }
    } catch {
        return @{ result = 'subscriber_error'; error_type = $_.Exception.GetBaseException().GetType().Name }
    } finally {
        $child.Dispose()
    }
}

$report = [ordered]@{
    collected_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
    gateway_id = $GatewayId
    gateway_discovery = Get-GatewayDiscovery
}
try {
    $network = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties()
    $bound = @($network.GetActiveTcpListeners() | Where-Object { $_.Port -eq $MqttPort })
    $report['mqtt_port'] = $MqttPort
    $report['mqtt_tcp_listener'] = $bound.Count -gt 0
    $report['mqtt_tcp_listener_on_lan_ipv4'] = @($bound | Where-Object {
        $_.Address.AddressFamily -eq [Net.Sockets.AddressFamily]::InterNetwork -and
        -not [Net.IPAddress]::IsLoopback($_.Address)
    }).Count -gt 0
    if ($GatewayIp) {
        $report['mqtt_tcp_connection_from_gateway'] = @($network.GetActiveTcpConnections() | Where-Object {
            $_.LocalEndPoint.Port -eq $MqttPort -and $_.RemoteEndPoint.Address.MapToIPv4().Equals($address) -and
            $_.State -eq [Net.NetworkInformation.TcpState]::Established
        }).Count -gt 0
    }
} catch {
    $report['mqtt_tcp_inspection_error'] = $_.Exception.GetBaseException().GetType().Name
}
$report['mqtt_status'] = Get-MqttStatus

try {
    $snapshot = Get-BridgeSnapshot
    if ($snapshot.ok -ne $true) { throw 'Bridge did not return an operational snapshot' }
    $selectedGateway = $snapshot.map_gateways | Where-Object gw -CEQ $GatewayId | Select-Object -First 1
    $report['bridge'] = @{
        result = 'snapshot_received'
        gateway_registered = $selectedGateway.registered -eq $true
        gateway_installed = $selectedGateway.kind -ceq 'installed' -and $selectedGateway.registered -eq $true
        gateway_online = $selectedGateway.online -eq $true
        gateway_status_age_s = $selectedGateway.age_s
    }
    if ($BandMac) {
        $employee = $snapshot.employees | Where-Object mac -EQ $BandMac | Select-Object -First 1
        $band = @($snapshot.bands | Where-Object { $_.mac -eq $BandMac -and $_.gw -ceq $GatewayId })
        $stage = $employee.manual_measurement.status
        $report['band'] = @{
            assigned = $employee.registered -eq $true
            monitoring_allowed = $employee.scan_allowed -eq $true
            present_in_bridge = $employee.present -eq $true
            bridge_reports_band_via_gateway = $band.Count -gt 0
            measurement_state = if ($stage -cin @('pending','queued','started','done','rejected','failed','timeout')) { $stage }
        }
    }
} catch {
    $report['bridge'] = @{ result = 'snapshot_unavailable'; error_type = $_.Exception.GetBaseException().GetType().Name }
}
$report | ConvertTo-Json -Depth 5
