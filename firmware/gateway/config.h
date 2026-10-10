// gateway/config.h — runtime configuration stored as JSON on LittleFS.
// Defaults are safe for desk testing; see firmware/gateway/README.md.
#pragma once

#include <Arduino.h>

struct GatewayConfig {
  char gw_id[24] = "gw-1";
  char zone[40] = "zone-1";
  char wifi_ssid[40] = "";
  char wifi_pass[80] = "";
  char mqtt_host[48] = "192.168.1.10";
  uint16_t mqtt_port = 1883;
  uint16_t health_interval_s = 600;  // health-window period (10 min)
  uint16_t scan_interval_ms = 160;   // BLE scan duty cycle (WiFi coexistence)
  uint16_t scan_window_ms = 80;
  uint16_t measure_timeout_s = 45;   // per-band measurement cap
};

// Loads /config.json from LittleFS into cfg; keeps defaults when the file is
// missing or invalid.
void configLoad(GatewayConfig& cfg);
