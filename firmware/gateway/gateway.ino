// Roztash factory health-monitoring gateway — ESP32 firmware skeleton.
//
// Roles:
//   A) continuous BLE scan for PDMB1062 bands  -> presence/RSSI batches (MQTT)
//   B) periodic "health windows": each known band is connected in turn, a
//      heart-rate measurement is started and its samples are collected, then
//      the band is released (disconnected) so advertising resumes.
//   C) remote commands on roztash/<gw>/cmd — currently "vibrate" (find-device):
//      connect, send (05,50), the band buzzes and acks, disconnect.
//   D) Ethernet setup uses the W5500 with DHCP; broker auto-discovery runs
//      only after Ethernet has received an IP address.
//
// Reference docs: docs/gateway-design.md, docs/band-protocol.md,
//                 docs/gateway-provisioning.md.
// Toolchain: arduino-cli + esp32 core 3.x + NimBLE-Arduino >= 2.1,
//            PubSubClient, ArduinoJson >= 7.
#include <Arduino.h>
#include <Network.h>
#include <ETH.h>
#include <SPI.h>
#include <esp_task_wdt.h>
#include <time.h>

#include "ble_central.h"
#include "config.h"
#include "mqtt_link.h"
#include "discovery.h"

const char* kFwVersion = "0.5.1-battery";

// SpO2 + HRV stages run only every Nth health window: three PPG measurements
// back to back on every window would drain the band's battery. Battery and
// device information are read on every connect (cheap GATT reads).
static const uint16_t kVitalsEveryN = 5;

static GatewayConfig cfg;
static BleCentral ble;
static MqttLink mqtt;

static uint32_t last_presence_ms = 0;
static uint32_t last_status_ms = 0;
static roztash::HealthSchedule health_schedule;
static DiscoveryClient discovery;
static bool broker_resolved = false;
static uint32_t last_broker_discovery_ms = 0;
static char resolved_mqtt_host[48] = {0};
static uint16_t resolved_mqtt_port = 1884;

// Resolve MQTT host via discovery after DHCP is ready; keep config as fallback.
static void resolveMqttHost() {
  strncpy(resolved_mqtt_host, cfg.mqtt_host, sizeof(resolved_mqtt_host) - 1);
  resolved_mqtt_host[sizeof(resolved_mqtt_host) - 1] = '\0';
  resolved_mqtt_port = cfg.mqtt_port;

  char discovered_host[sizeof(resolved_mqtt_host)] = {0};
  uint16_t discovered_port = resolved_mqtt_port;
  const bool found = discovery.discover(cfg.mqtt_host, cfg.mqtt_port,
                                        discovered_host, sizeof discovered_host,
                                        &discovered_port);
  if (found) {
    strncpy(resolved_mqtt_host, discovered_host, sizeof(resolved_mqtt_host) - 1);
    resolved_mqtt_host[sizeof(resolved_mqtt_host) - 1] = '\0';
    resolved_mqtt_port = discovered_port;
  }
  mqtt.setBroker(resolved_mqtt_host, resolved_mqtt_port);
  Serial.printf("[gw] broker: %s:%u%s\n", resolved_mqtt_host,
                resolved_mqtt_port, found ? " (discovered)" : " (config fallback)");
  broker_resolved = true;
}

// Consume one assigned MAC, even when absent or a connection fails. Advancing
// by MAC snapshot avoids slot reuse/expiry making an employee repeat or vanish.
static void pickNextBand() {
  roztash::PolicyMac mac{};
  const uint32_t now = millis();
  if (!health_schedule.next(mqtt.policy(), now, mac)) return;
  if (!ble.hasFreshSighting(mac.data(), now)) {
    mqtt.publishEvent("measure_unavailable", mac.data(), "no fresh advertisement within 60s");
    return;
  }
  const bool vitals = (health_schedule.generation() % kVitalsEveryN) == 0;
  if (!ble.startHealth(mac.data(), vitals))
    mqtt.publishEvent("measure_fail", mac.data(), "job could not start");
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
  ble.begin(cfg.scan_interval_ms, cfg.scan_window_ms,
            (uint32_t)cfg.measure_timeout_s * 1000UL);

  broker_resolved = false;
  last_broker_discovery_ms = 0;
  last_presence_ms = millis();
  last_status_ms = millis();
  Serial.println("[gw] BLE ready; waiting for Ethernet DHCP");
}

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n[gw] boot — fw %s\n", kFwVersion);

  configLoad(cfg);
  setupWatchdog();

  mqtt.begin(cfg, ble, health_schedule);  // W5500 DHCP, then leased BLE policy
  normalBegin();
  Serial.println("[gw] ready");
}

void loop() {
  mqtt.poll();
  const uint32_t now = millis();

  // Discover the HSE broker only after W5500 has link and a DHCP lease.
  if (mqtt.networkReady() && !broker_resolved &&
      now - last_broker_discovery_ms >= 1000) {
    last_broker_discovery_ms = now;
    resolveMqttHost();
  }

  // BLE control task enforces lease expiry even during network calls.

  // A) presence batch every 10 s
  if (now - last_presence_ms >= 10000) {
    last_presence_ms = now;
    ble.pruneStale(now, 60000);
    mqtt.publishPresence(ble);
  }

  // B) sequential health windows. No catch-up overlap when a cycle overruns.
  if (!ble.healthBusy() && !ble.jobFinished() && health_schedule.openIfDue(mqtt.policy(), millis()))
    Serial.printf("[gw] health window %lu open\n", (unsigned long)health_schedule.generation());
  if (!ble.healthBusy()) {
    if (ble.jobFinished()) {
      if (ble.wasVibrate()) {
        if (ble.jobRevoked() || !mqtt.policy().allows(ble.jobMac(), millis()))
          mqtt.rejectVibration("policy_revoked");
        else mqtt.finishVibration(ble.vibrated());
      } else if (ble.jobRevoked() || !mqtt.policy().allows(ble.jobMac(), millis())) {
        // Discard all results of revoked work; do not leak an off-duty sample.
      } else {
        mqtt.publishHealth(ble);
        mqtt.publishVitals(ble);
        if (ble.state() == BleCentral::JobState::Failed)
          mqtt.publishEvent("measure_fail", ble.jobMac(), "");
        else if (!ble.wearingOk())
          mqtt.publishEvent("wearing_error", ble.jobMac(), "");
      }
      ble.clearJob();
    } else {
      // Commands get a turn between jobs; never overlap a health connection.
      char act[16] = {0};
      char cmac[20] = {0};
      if (mqtt.takeCommand(act, sizeof act, cmac, sizeof cmac)) {
        if (strcmp(act, "vibrate") == 0) {
          if (!ble.startVibrate(cmac))
            mqtt.rejectVibration("off_duty_unseen_or_busy");
        } else mqtt.publishEvent("cmd_unknown", cmac, act);
      } else if (health_schedule.active()) pickNextBand();
    }
  }

  // C) immediate status on connect/policy change, then every 60 seconds.
  if (mqtt.takeStatusRequest() || now - last_status_ms >= 60000) {
    last_status_ms = now;
    mqtt.publishStatus(kFwVersion, ETH.localIP().toString().c_str(),
                       ble.sightingCount(), ble.advCount());
  }

  esp_task_wdt_reset();
  delay(10);
}
