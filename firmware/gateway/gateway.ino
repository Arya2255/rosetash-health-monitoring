// Roztash factory health-monitoring gateway — ESP32 firmware skeleton.
//
// Roles:
//   A) continuous BLE scan for PDMB1062 bands  -> presence/RSSI batches (MQTT)
//   B) periodic "health windows": each known band is connected in turn, a
//      heart-rate measurement is started and its samples are collected, then
//      the band is released (disconnected) so advertising resumes.
//   C) remote commands on roztash/<gw>/cmd — currently "vibrate" (find-device):
//      connect, send (05,50), the band buzzes and acks, disconnect.
//   D) wifi setup portal: when wifi config is missing or the station fails to
//      connect, an open AP "RoztashGw-XXXXXX" serves a phone setup page
//      (setup_portal.{h,cpp}) — config only; firmware itself needs one USB flash.
//
// Reference docs: docs/gateway-design.md, docs/band-protocol.md,
//                 docs/gateway-provisioning.md.
// Toolchain: arduino-cli + esp32 core 3.x + NimBLE-Arduino >= 2.1,
//            PubSubClient, ArduinoJson >= 7.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_task_wdt.h>
#include <time.h>

#include "ble_central.h"
#include "config.h"
#include "mqtt_link.h"
#include "discovery.h"
#include "setup_portal.h"

const char* kFwVersion = "0.3.0-discovery";

// SpO2 + HRV stages run only every Nth health window: three PPG measurements
// back to back on every window would drain the band's battery. Battery and
// device information are read on every connect (cheap GATT reads).
static const uint16_t kVitalsEveryN = 5;

static GatewayConfig cfg;
static BleCentral ble;
static MqttLink mqtt;

static uint32_t last_presence_ms = 0;
static uint32_t last_status_ms = 0;
static uint32_t window_started_ms = 0;
static bool window_active = false;
static uint16_t window_gen = 1;
static uint16_t attempted_gen[BleCentral::kMaxBands];  // per-sighting-slot
static DiscoveryClient discovery;
static char resolved_mqtt_host[48] = {0};
static uint16_t resolved_mqtt_port = 1884;

// Resolve MQTT host via discovery, fallback to config
static void resolveMqttHost() {
  // DEBUG: Skip discovery - use config directly
  strncpy(resolved_mqtt_host, cfg.mqtt_host, sizeof(resolved_mqtt_host) - 1);
  resolved_mqtt_port = cfg.mqtt_port;
  
  Serial.printf("[gw] Discovery: DISABLED, using config %s:%u\n", resolved_mqtt_host, resolved_mqtt_port);
}

// Picks the next band not yet measured in this window.
static bool pickNextBand() {
  const uint32_t now = millis();
  for (int slot = 0; slot < BleCentral::kMaxBands; ++slot) {
    BleCentral::Sighting s;
    if (!ble.getSlot(slot, s) || !s.used) continue;
    if (attempted_gen[slot] == window_gen) continue;
    if ((now - s.seen_ms) > 120000) continue;  // stale sighting, skip
    attempted_gen[slot] = window_gen;
    const bool vitals = (window_gen % kVitalsEveryN) == 0;
    return ble.startHealth(s.mac, vitals);
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

static void normalBegin() {
  configTime(0, 0, "pool.ntp.org", "time.google.com");  // UTC; backend localizes

  // Resolve MQTT server via discovery (auto-find the PC)
  resolveMqttHost();
  
  // Override config with discovered values
  strncpy(cfg.mqtt_host, resolved_mqtt_host, sizeof(cfg.mqtt_host) - 1);
  cfg.mqtt_port = resolved_mqtt_port;
  
  ble.begin(cfg.scan_interval_ms, cfg.scan_window_ms,
            (uint32_t)cfg.measure_timeout_s * 1000UL);
  mqtt.begin(cfg);

  window_started_ms = millis();
  last_presence_ms = millis();
  last_status_ms = millis();
  Serial.println("[gw] ready");
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n[gw] boot — fw %s\n", kFwVersion);

  configLoad(cfg);
  setupWatchdog();

  // wifi: connect when configured; otherwise — or when the station fails —
  // open the setup portal (AP + web page) so the gateway can be configured
  // from a phone. The portal keeps retrying and hands over transparently.
  bool wifi_ok = false;
  if (cfg.wifi_ssid[0]) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(cfg.wifi_ssid, cfg.wifi_pass);
    const uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < 90000) {
      delay(500);
      Serial.print(".");
      esp_task_wdt_reset();
    }
    wifi_ok = WiFi.status() == WL_CONNECTED;
  }
  Serial.printf("[gw] wifi: %s\n",
                wifi_ok ? WiFi.localIP().toString().c_str()
                        : (cfg.wifi_ssid[0] ? "connect failed — setup mode"
                                            : "no config — setup mode"));
  if (!wifi_ok) {
    setupPortalBegin(cfg);
  } else {
    normalBegin();
  }
}

void loop() {
  const uint32_t now = millis();

  // Setup portal: serve the config page; the station retries in the
  // background and we fall through to normal operation once it connects.
  if (setupPortalActive()) {
    if (setupPortalPoll()) {
      WiFi.setAutoReconnect(true);
      normalBegin();
    }
    esp_task_wdt_reset();
    delay(10);
    return;
  }

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
      if (ble.wasVibrate()) {
        mqtt.publishEvent(ble.vibrated() ? "vibrated" : "vibrate_fail", ble.jobMac(),
                          "");
        Serial.printf("[gw] vibrate result: ack=%d\n", (int)ble.vibrated());
      } else {
        mqtt.publishHealth(ble);
        mqtt.publishVitals(ble);  // battery / device info / SpO2+HRV frames
        if (ble.state() == BleCentral::JobState::Failed)
          mqtt.publishEvent("measure_fail", ble.jobMac(), "");
        else if (!ble.wearingOk())
          mqtt.publishEvent("wearing_error", ble.jobMac(), "");
      }
      ble.clearJob();
    } else {
      if (window_active && !pickNextBand()) {
        window_active = false;  // every candidate attempted
        Serial.println("[gw] health window closed");
      }
      // D) remote commands (vibrate) — run whenever no measurement is in flight
      if (!window_active) {
        char act[16] = {0};
        char cmac[20] = {0};
        if (mqtt.takeCommand(act, sizeof act, cmac, sizeof cmac)) {
          if (strcmp(act, "vibrate") == 0 && cmac[0]) {
            if (!ble.startVibrate(cmac))
              mqtt.publishEvent("cmd_reject", cmac, "vibrate: not seen or busy");
            else
              Serial.printf("[gw] vibrate command -> %s\n", cmac);
          } else if (strcmp(act, "vibrate") == 0) {
            mqtt.publishEvent("cmd_reject", cmac, "vibrate: missing mac");
          } else {
            mqtt.publishEvent("cmd_unknown", cmac, act);
          }
        }
      }
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
