#include "config.h"

#include <ArduinoJson.h>
#include <LittleFS.h>

static void copyStr(char* dst, size_t dst_len, const char* src) {
  if (!src) return;
  strlcpy(dst, src, dst_len);
}

void configLoad(GatewayConfig& cfg) {
  if (!LittleFS.begin(true)) {
    Serial.println("[cfg] LittleFS mount failed — using defaults");
    return;
  }
  File f = LittleFS.open("/config.json", "r");
  if (!f) {
    Serial.println("[cfg] /config.json not found — using defaults");
    return;
  }
  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, f);
  f.close();
  if (err) {
    Serial.printf("[cfg] config.json parse error (%s) — using defaults\n",
                  err.c_str());
    return;
  }
  copyStr(cfg.gw_id, sizeof cfg.gw_id, doc["gw_id"] | "gw-1");
  copyStr(cfg.zone, sizeof cfg.zone, doc["zone"] | "zone-1");
  copyStr(cfg.wifi_ssid, sizeof cfg.wifi_ssid, doc["wifi_ssid"] | "");
  copyStr(cfg.wifi_pass, sizeof cfg.wifi_pass, doc["wifi_pass"] | "");
  copyStr(cfg.mqtt_host, sizeof cfg.mqtt_host, doc["mqtt_host"] | "192.168.1.10");
  cfg.mqtt_port = doc["mqtt_port"] | 1883;
  cfg.health_interval_s = doc["health_interval_s"] | 600;
  cfg.scan_interval_ms = doc["scan_interval_ms"] | 160;
  cfg.scan_window_ms = doc["scan_window_ms"] | 80;
  cfg.measure_timeout_s = doc["measure_timeout_s"] | 45;
  Serial.printf("[cfg] loaded: gw=%s zone=%s broker=%s:%u\n", cfg.gw_id,
                cfg.zone, cfg.mqtt_host, (unsigned)cfg.mqtt_port);
}
