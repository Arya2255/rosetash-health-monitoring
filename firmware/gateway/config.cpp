#include "config.h"

#include <ArduinoJson.h>
#include <LittleFS.h>
#include <ETH.h>

// آی‌پی ثابت ESP32 (باید با subnet HSE یکی باشد)
static const IPAddress STATIC_IP(192, 168, 50, 100);
static const IPAddress STATIC_GW(192, 168, 50, 1);
static const IPAddress STATIC_SUBNET(255, 255, 255, 0);
static const IPAddress STATIC_DNS(8, 8, 8, 8);

static void copyStr(char* dst, size_t dst_len, const char* src) {
  if (!src) return;
  strlcpy(dst, src, dst_len);
}

void configLoad(GatewayConfig& cfg) {
  // Defaults for the dedicated HSE Ethernet network.
  strlcpy(cfg.gw_id, "gw-1", sizeof(cfg.gw_id));
  strlcpy(cfg.zone, "zone-1", sizeof(cfg.zone));
  strlcpy(cfg.mqtt_host, "192.168.50.10", sizeof(cfg.mqtt_host));  // آدرس HSE (ویندوز)
  cfg.mqtt_port = 1884;
  cfg.health_interval_s = 600;
  cfg.scan_interval_ms = 160;
  cfg.scan_window_ms = 80;
  cfg.measure_timeout_s = 45;

  if (!LittleFS.begin(true)) {
    Serial.println("[cfg] LittleFS mount failed — using defaults");
    return;
  }
  File f = LittleFS.open("/config.json", "r");
  if (!f) {
    Serial.println("[cfg] /config.json not found — using defaults");
    // تنظیم W5500 با آی‌پی ثابت
    ETH.begin(ETH_PHY_W5500, 5, 21, 18, SPI, 1);
    ETH.config(STATIC_IP, STATIC_GW, STATIC_SUBNET, STATIC_DNS);
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
  copyStr(cfg.mqtt_host, sizeof cfg.mqtt_host,
          doc["mqtt_host"] | "192.168.50.10");
  cfg.mqtt_port = doc["mqtt_port"] | 1884;

  cfg.health_interval_s = doc["health_interval_s"] | 600;
  cfg.scan_interval_ms = doc["scan_interval_ms"] | 160;
  cfg.scan_window_ms = doc["scan_window_ms"] | 80;
  cfg.measure_timeout_s = doc["measure_timeout_s"] | 45;

  // تنظیم W5500 با آی‌پی ثابت
  ETH.begin(ETH_PHY_W5500, 5, 21, 18, SPI, 1);
  ETH.config(STATIC_IP, STATIC_GW, STATIC_SUBNET, STATIC_DNS);
  Serial.printf("[cfg] loaded: gw=%s zone=%s broker=%s:%u ip=%s\n",
                cfg.gw_id, cfg.zone, cfg.mqtt_host, (unsigned)cfg.mqtt_port,
                STATIC_IP.toString().c_str());
}
