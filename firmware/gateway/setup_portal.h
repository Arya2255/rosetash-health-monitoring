// gateway/setup_portal.h — AP configuration portal for unconfigured gateways.
//
// When the board has no wifi config (fresh board / blank LittleFS) or the
// station connection fails (e.g. wrong password), the gateway starts a small
// open access point "RoztashGw-XXXXXX" (last 3 MAC bytes) and serves a
// Persian setup page on http://192.168.4.1 so wifi + identity can be set
// from a phone. Config-only: the firmware itself must be written once over USB.
//
// While the portal is open the station keeps retrying with the stored
// credentials; as soon as it connects, the portal shuts down and the caller
// continues with normal operation (BLE scan + MQTT).
#pragma once

#include "config.h"

// Single firmware version string — defined in gateway.ino, printed here too.
extern const char* kFwVersion;

// True while the portal (AP + web server) is running.
bool setupPortalActive();

// Starts the AP + web server. Idempotent. Call when wifi is missing/broken.
void setupPortalBegin(const GatewayConfig& cfg);

// Serves the portal and retries the station connection. Returns true when
// the station got connected and the portal was shut down — the caller then
// proceeds with normal subsystems (BLE + MQTT).
bool setupPortalPoll();
