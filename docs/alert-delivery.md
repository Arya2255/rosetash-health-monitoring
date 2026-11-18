# Durable staff-alert delivery

The bridge stores one open episode per eligible source/issue/context and one
request ID per episode/recipient. Every registered HSE recipient uses the
emergency command path. The local unit contact uses ordinary on-duty permission.
`active_macs` contains on-duty bands; `emergency_macs` separately permits HSE
presence and emergency vibration, including outside their monitoring schedule.
`health_macs` remains the gateway-specific measurement assignment.

A successful MQTT publish means sent, not confirmed. Only a matching target,
gateway, request ID, reason and three completed pulses confirms staff delivery.
Malformed, replayed and unrelated results do not confirm it. Confirmations and
partial counts persist across bridge database reopen. A publish failure cannot
overwrite a confirmation already received during that call.

If a source recovers, leaves its monitoring schedule, is paused/removed or loses
the warning from its current view, its open episode closes. Later warnings get
new episode/request IDs. A closed episode is not retried.

## Retry boundary

Retries use the original gateway and request ID, carrying the largest reported
partial count. Attempts are bounded to three with a 120-second retry interval
and a 480-second retry window. Expiry is evaluated even if the gateway or band is
unavailable. An expired/unconfirmed staff request no longer reserves the gateway
slot indefinitely for other staff/battery notifications.

There is deliberately no automatic cross-gateway failover after a send: another
gateway does not share the first gateway's duplicate cache and could repeat an
unreported physical effect. An unconfirmed delivery remains visible in stored
state; it is not relabeled as success. The firmware's duplicate/partial cache is
in memory and is not an exactly-once guarantee across a gateway restart.

## Firmware ACK handling

The BLE worker sends one find-device write at a time. Only the documented
CRC-valid `(05,50,[00])` response advances its acknowledged count. Duplicate
notifications in the same burst do not advance it again. The next write waits
at least 250 ms. A retry with two completed pulses sends one remaining write.

An ACK queued while permission was valid is consumed before the result is handed
back, including during disconnect or policy revocation. New notifications after
revocation remain blocked. Revocation results carry the current completed count
into the MQTT result and duplicate cache, so a later retry does not restart from
its original count. Health samples retain their policy checks.

## Evidence and remaining physical checks

Host tests execute the production BLE worker with controlled hardware/task
boundaries, including actual frame writes, queued notifications, invalid replies,
resume, timeout, disconnect and revocation ordering. They do not prove radio or
FreeRTOS scheduling on a physical board. The package is also freshly compiled
for the configured ESP32-S3 N16R8 and independently checked against its manifest.

A delayed duplicate from an earlier write arriving only after the next write is
pending cannot be reliably distinguished by opcode/payload alone. The captured
find-device ACK is insufficient to establish per-write counter echo semantics;
no unverified counter assumption is enforced. This needs live multi-write
captures before claiming delayed-duplicate correlation or exactly three physical
vibrations. A device ACK establishes protocol receipt; physical vibration still
requires the wearer's observation.

Physical flashing, boot, Ethernet/DHCP/MQTT and the three perceived vibrations
remain separate acceptance checks. A partition-layout mismatch must be resolved
with the owner before replacing the device's partition table or filesystem.

## Local checks

```bash
TMPDIR="$HOME/.hermes/cache/scratch" bash firmware/test/run_policy_tests.sh
TMPDIR="$HOME/.hermes/cache/scratch" bash firmware/test/run_host_test.sh
PYTHONPATH="$PWD" .venv/bin/python -B tests/test_alert_delivery.py
PYTHONPATH="$PWD" .venv/bin/python -B tests/test_monitoring_runtime.py
.venv/bin/python -B tools/build_provisioner_bundle.py
.venv/bin/python -B scripts/validate_windows_single.py --inputs-only
```
