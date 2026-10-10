// Roztash factory health-monitoring gateway — ESP32 firmware skeleton.
//
// Roles:
//   A) continuous BLE scan for PDMB1062 bands  -> presence/RSSI batches (MQTT)
//   B) periodic "health windows": each known band is connected in turn, a
//      heart-rate measurement is started and its samples are collected, then
//      the band is released (disconnected) so advertising resumes.
//
// Reference docs: docs/gateway-design.md, docs/band-protocol.md.
// Toolchain: arduino-cli + esp32 core 3.x + NimBLE-Arduino >= 2.1,
//            PubSubClient, ArduinoJson >= 7.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_task_wdt.h>
#include <time.h>

#include "ble_central.h"
#include "config.h"
#include "mqtt_link.h"

static const char* kFwVersion = "0.1.3-skeleton";

static GatewayConfig cfg;
static BleCentral ble;
static MqttLink mqtt;

static uint32_t last_presence_ms = 0;
static uint32_t last_status_ms = 0;
static uint32_t window_started_ms = 0;
static bool window_active = false;
static uint16_t window_gen = 1;
static uint16_t attempted_gen[BleCentral::kMaxBands];  // per-sighting-slot

// Picks the next band not yet measured in this window.
static bool pickNextBand() {
  const uint32_t now = millis();
  for (int slot = 0; slot < BleCentral::kMaxBands; ++slot) {
    BleCentral::Sighting s;
    if (!ble.getSlot(slot, s) || !s.used) continue;
    if (attempted_gen[slot] == window_gen) continue;
    if ((now - s.seen_ms) > 120000) continue;  // stale sighting, skip
    attempted_gen[slot] = window_gen;
    return ble.startHealth(s.mac);
  }
  return false;
}

static void setupWatchdog() {
  esp_task_wdt_config_t twdt = {
      .timeout_ms = 30000,
      .idle_core_mask = 0,
      .trigger_panic = true,
  };
  esp_task_wdt_reconfigure(&twdt);  // core 3.x: reconfigure instead of init
  esp_task_wdt_add(NULL);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n[gw] boot — fw %s\n", kFwVersion);

  configLoad(cfg);

  WiFi.begin(cfg.wifi_ssid, cfg.wifi_pass);
  const uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) delay(250);
  Serial.printf("[gw] wifi: %s\n",
                WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str()
                                              : "not connected (continuing)");

  configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC; backend localizes

  ble.begin(cfg.scan_interval_ms, cfg.scan_window_ms,
            (uint32_t)cfg.measure_timeout_s * 1000UL);
  mqtt.begin(cfg);

  window_started_ms = millis();
  setupWatchdog();
  Serial.println("[gw] ready");
}

void loop() {
  const uint32_t now = millis();

  mqtt.poll();
  ble.poll();

  // A) presence batch every 10 s
  if (now - last_presence_ms >= 10000) {
    last_presence_ms = now;
    ble.pruneStale(now, 60000);
    mqtt.publishPresence(ble);
  }

  // B) health windows
  if (!window_active &&
      (now - window_started_ms) >= (uint32_t)cfg.health_interval_s * 1000UL) {
    window_active = true;
    window_started_ms = now;
    window_gen++;
    Serial.printf("[gw] health window %u open (%d bands seen)\n",
                  (unsigned)window_gen, ble.sightingCount());
  }
  if (!ble.healthBusy()) {
    if (ble.jobFinished()) {
      mqtt.publishHealth(ble);
      if (ble.state() == BleCentral::JobState::Failed)
        mqtt.publishEvent("measure_fail", ble.jobMac(), "");
      else if (!ble.wearingOk())
        mqtt.publishEvent("wearing_error", ble.jobMac(), "");
      ble.clearJob();
    } else if (window_active && !pickNextBand()) {
      window_active = false;  // every candidate attempted
      Serial.println("[gw] health window closed");
    }
  }

  // C) status heartbeat every 60 s
  if (now - last_status_ms >= 60000) {
    last_status_ms = now;
    mqtt.publishStatus(kFwVersion, WiFi.RSSI(),
                       WiFi.localIP().toString().c_str(),
                       ble.sightingCount(), ble.advCount());
  }

  esp_task_wdt_reset();
  delay(10);
}
