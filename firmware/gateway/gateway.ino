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
#include "broker_discovery_retry.h"

const char* kFwVersion = "0.5.3-operational";

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
static GatewayDiscoveryResponder gateway_discovery;
static roztash::BrokerDiscoveryRetry broker_retry;
static bool network_was_ready = false;
static char last_network_ip[16] = {0};
static uint32_t last_gateway_discovery_attempt_ms = 0;
static char resolved_mqtt_host[48] = {0};
static uint16_t resolved_mqtt_port = 1884;

// Resolve MQTT host via discovery after DHCP is ready; keep config as fallback.
static void resolveMqttHost() {
  if (!discovery.active()) {
    if (!discovery.start()) {
      broker_retry.recordFailure(millis());
      Serial.println("[gw] broker discovery socket unavailable; retrying");
      return;
    }
    Serial.println("[gw] broker discovery query sent");
    return;
  }

  char discovered_host[sizeof(resolved_mqtt_host)] = {0};
  uint16_t discovered_port = cfg.mqtt_port;
  const auto result = discovery.poll(discovered_host, sizeof discovered_host, &discovered_port);
  if (result == DiscoveryClient::PollResult::Success) {
    broker_retry.recordSuccess(discovered_host, discovered_port, millis());
    strncpy(resolved_mqtt_host, discovered_host, sizeof(resolved_mqtt_host) - 1);
    resolved_mqtt_host[sizeof(resolved_mqtt_host) - 1] = '\0';
    resolved_mqtt_port = discovered_port;
    mqtt.setBroker(resolved_mqtt_host, resolved_mqtt_port);
    Serial.printf("[gw] broker: %s:%u (discovered)\n", resolved_mqtt_host,
                  resolved_mqtt_port);
  } else if (result == DiscoveryClient::PollResult::Failure) {
    broker_retry.recordFailure(millis());
    strncpy(resolved_mqtt_host, cfg.mqtt_host, sizeof(resolved_mqtt_host) - 1);
    resolved_mqtt_host[sizeof(resolved_mqtt_host) - 1] = '\0';
    resolved_mqtt_port = cfg.mqtt_port;
    mqtt.setBroker(resolved_mqtt_host, resolved_mqtt_port);
    Serial.printf("[gw] broker: %s:%u (config fallback; discovery retrying)\n",
                  resolved_mqtt_host, resolved_mqtt_port);
  }
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

  broker_retry = roztash::BrokerDiscoveryRetry{};
  network_was_ready = false;
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
  const bool network_ready = mqtt.networkReady();
  if (network_ready) {
    const String ip = ETH.localIP().toString();
    if (last_network_ip[0] && ip != last_network_ip) {
      broker_retry.networkReady();
      discovery.cancel();
      Serial.printf("[gw] DHCP address changed: %s; refreshing broker discovery\n", ip.c_str());
    }
    strncpy(last_network_ip, ip.c_str(), sizeof(last_network_ip) - 1);
    last_network_ip[sizeof(last_network_ip) - 1] = '\0';
  } else last_network_ip[0] = '\0';
  if (network_ready && !network_was_ready) {
    broker_retry.networkReady();
  } else if (!network_ready && network_was_ready) {
    broker_retry.networkLost();
    discovery.cancel();
    gateway_discovery.stop();
    last_gateway_discovery_attempt_ms = 0;
  }
  network_was_ready = network_ready;
  if (network_ready && !gateway_discovery.active() &&
      (last_gateway_discovery_attempt_ms == 0 ||
       uint32_t(now - last_gateway_discovery_attempt_ms) >= 5000)) {
    last_gateway_discovery_attempt_ms = now ? now : 1;
    gateway_discovery.begin(cfg.gw_id, kFwVersion);
  }
  gateway_discovery.poll(mqtt.online());

  // Discover the HSE broker only after W5500 has link and a DHCP lease.
  if (network_ready && (discovery.active() || broker_retry.due(now))) {
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
        if (ble.vibrated()) mqtt.finishVibration(true, ble.vibrateAcks());
        else if (ble.jobRevoked() || (ble.wasVibrateEmergency()
            ? !mqtt.policy().allowsEmergency(ble.jobMac(), millis())
            : !mqtt.policy().allows(ble.jobMac(), millis())))
          mqtt.rejectVibration("policy_revoked", ble.vibrateAcks());
        else mqtt.finishVibration(false, ble.vibrateAcks());
      } else if (ble.wasManualMeasure()) {
        if (ble.jobRevoked() || !mqtt.policy().allowsHealth(ble.jobMac(), millis())) {
          mqtt.finishManualMeasure("measure_reject", "policy_revoked");
        } else {
          const bool health_published = mqtt.publishHealth(ble);
          mqtt.publishVitals(ble);
          if (ble.state() == BleCentral::JobState::Done && ble.validHrSampleCount() > 0 &&
              health_published)
            mqtt.finishManualMeasure("measure_done");
          else
            mqtt.finishManualMeasure("measure_fail", ble.state() != BleCentral::JobState::Done
                ? "health_job_failed" : (ble.validHrSampleCount() == 0
                    ? "no_hr_samples" : "health_publish_failed"));
        }
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
      char request_id[65] = {0};
      bool vitals = false;
      bool emergency = false;
      uint8_t repeats = 1;
      uint8_t completed_pulses = 0;
      if (mqtt.takeManualMeasure(cmac, sizeof cmac, &vitals, request_id,
                                 sizeof request_id)) {
        if (!ble.startHealth(cmac, vitals, request_id))
          mqtt.finishManualMeasure("measure_fail", "job_could_not_start");
        else
          mqtt.manualMeasureStarted();
      } else if (mqtt.takeCommand(act, sizeof act, cmac, sizeof cmac, &emergency,
                           &repeats, &completed_pulses)) {
        if (strcmp(act, "vibrate") == 0) {
          if (!ble.startVibrate(cmac, emergency, repeats, completed_pulses))
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
