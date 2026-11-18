#include "mqtt_link.h"

#include <ArduinoJson.h>
#include <ETH.h>
#include <LittleFS.h>
#include <SPI.h>

#include "network_config.h"
#include "scan_policy_json.h"

static const char* kQueuePath = "/queue.jsonl";
static const size_t kQueueMaxBytes = 32 * 1024;  // drop oldest wholesale when full
static bool ethernet_started = false;

static void onNetworkEvent(arduino_event_id_t event) {
  switch (event) {
    case ARDUINO_EVENT_ETH_START:
      ETH.setHostname("roztash-gateway");
      Serial.println("[eth] W5500 started; waiting for link and DHCP");
      break;
    case ARDUINO_EVENT_ETH_CONNECTED:
      Serial.println("[eth] cable link up; DHCP address pending");
      break;
    case ARDUINO_EVENT_ETH_GOT_IP:
      Serial.printf("[eth] DHCP IP: %s  mask: %s  gateway: %s\n",
                    ETH.localIP().toString().c_str(),
                    ETH.subnetMask().toString().c_str(),
                    ETH.gatewayIP().toString().c_str());
      break;
    case ARDUINO_EVENT_ETH_LOST_IP:
      Serial.println("[eth] DHCP address lost");
      break;
    case ARDUINO_EVENT_ETH_DISCONNECTED:
      Serial.println("[eth] cable disconnected");
      break;
    case ARDUINO_EVENT_ETH_STOP:
      Serial.println("[eth] stopped");
      break;
    default:
      break;
  }
}

static bool startEthernet() {
  if (ethernet_started) return true;
  Network.onEvent(onNetworkEvent);
  SPI.begin(roztash::kW5500Sck, roztash::kW5500Miso,
            roztash::kW5500Mosi, roztash::kW5500Cs);
  ETH.setPollPeriod(25);  // W5500 INT is not connected.
  ethernet_started = ETH.begin(ETH_PHY_W5500, 1, roztash::kW5500Cs,
                               roztash::kW5500Irq, roztash::kW5500Rst,
                               SPI, roztash::kW5500SpiMhz);
  Serial.printf("[eth] ETH.begin: %s\n", ethernet_started ? "OK" : "FAILED");
  return ethernet_started;
}

static const char* failName(BleCentral::Fail f) {
  switch (f) {
    case BleCentral::Fail::None: return "none";
    case BleCentral::Fail::Connect: return "connect";
    case BleCentral::Fail::Subscribe: return "subscribe";
    case BleCentral::Fail::Write: return "write";
    case BleCentral::Fail::Timeout: return "timeout";
    case BleCentral::Fail::Policy: return "policy";
  }
  return "?";
}

void MqttLink::begin(const GatewayConfig& cfg, BleCentral& ble, roztash::HealthSchedule& schedule) {
  ble_ = &ble;
  schedule_ = &schedule;
  cfg_ = cfg;
  snprintf(base_, sizeof base_, "roztash/%s", cfg_.gw_id);

  startEthernet();

  mqtt_.setServer(cfg_.mqtt_host, cfg_.mqtt_port);
  buffer_ready_ = mqtt_.setBufferSize(16384);  // both 256-MAC arrays plus envelope
  mqtt_.setSocketTimeout(2);
  if (!buffer_ready_) Serial.println("[mqtt] scan_policy_error: buffer allocation failed");

  // Remote commands (roztash/<gw>/cmd). The callback runs inside mqtt_.loop()
  // (single task) — parsing here and handing over via takeCommand() is safe.
  mqtt_.setCallback([this](char* topic, uint8_t* payload, unsigned int len) {
    char expected[64];
    snprintf(expected, sizeof expected, "%s/scan-policy", base_);
    if (strcmp(topic, expected) == 0) {
      if (net_.guard.retained()) {
        revokePolicy();
        publishEvent("scan_policy_error", "", "retained_policy_rejected");
      } else receivePolicy(payload, len);
      return;
    }
    snprintf(expected, sizeof expected, "%s/cmd", base_);
    if (strcmp(topic, expected) != 0) return;

    if (roztash::isManualMeasureAction(reinterpret_cast<const char*>(payload), len)) {
      const bool retained = net_.guard.retained();
      roztash::ManualMeasureCommand command;
      const char* error = nullptr;
      if (!roztash::parseManualMeasureCommand(reinterpret_cast<const char*>(payload), len,
                                              command, error)) {
        publishManualEvent("measure_reject", command, error);
        return;
      }
      if (retained) {
        publishManualEvent("measure_reject", command, "retained_command_rejected");
        return;
      }
      const uint32_t now = millis();
      if (!policy_.allowsHealth(command.mac, now) ||
          !ble_->hasFreshSighting(command.mac, now)) {
        publishManualEvent("measure_reject", command, "off_duty_unseen_or_policy");
        return;
      }
      switch (manual_measurements_.offer(command, now)) {
        case roztash::ManualMeasureOffer::Accepted:
          status_pending_ = true;
          publishManualEvent("measure_queued", command, "");
          break;
        case roztash::ManualMeasureOffer::Duplicate:
          publishManualEvent("measure_queued", command, "duplicate_request");
          break;
        case roztash::ManualMeasureOffer::Conflict:
          publishManualEvent("measure_reject", command, "request_id_conflict");
          break;
        case roztash::ManualMeasureOffer::Busy:
          publishManualEvent("measure_reject", command, "manual_measure_queue_busy");
          break;
      }
      return;
    }

    roztash::VibrationCommand command;
    const char* error = nullptr;
    if (!roztash::parseVibrationCommand(reinterpret_cast<const char*>(payload), len,
                                       command, error)) {
      publishEvent("cmd_reject", "", error);
      return;
    }
    if (net_.guard.retained()) {
      publishCommandEvent("cmd_reject", command, "retained_command_rejected");
      return;
    }
    if (command.emergency ? !policy_.allowsEmergency(command.mac, millis())
                          : !policy_.allows(command.mac, millis())) {
      publishCommandEvent("cmd_reject", command, "policy_revoked");
      return;
    }
    switch (vibration_commands_.offer(command, millis())) {
      case roztash::CommandOffer::Completed: {
        auto completed = command;
        completed.completed_pulses = vibration_commands_.completedPulses(command, millis());
        publishCommandEvent("vibrated", completed, "already_completed");
        break;
      }
      case roztash::CommandOffer::Conflict:
        publishCommandEvent("cmd_reject", command, "request_id_conflict"); break;
      case roztash::CommandOffer::Busy:
        publishCommandEvent("cmd_reject", command, "command_queue_busy"); break;
      case roztash::CommandOffer::Duplicate:
      case roztash::CommandOffer::Accepted:
        break;
    }
  });
}

void MqttLink::setBroker(const char* host, uint16_t port) {
  if (!host || !host[0]) return;
  if (std::strcmp(cfg_.mqtt_host, host) == 0 && cfg_.mqtt_port == port) return;
  revokePolicy();
  if (mqtt_.connected()) mqtt_.disconnect();
  strlcpy(cfg_.mqtt_host, host, sizeof cfg_.mqtt_host);
  cfg_.mqtt_port = port;
  mqtt_.setServer(cfg_.mqtt_host, cfg_.mqtt_port);
}

bool MqttLink::networkReady() const {
  return ethernet_started && ETH.linkUp() && ETH.hasIP();
}

// --- connection maintenance -------------------------------------------------
void MqttLink::poll() {
  const uint32_t now = millis();
  if (policy_.expire(now)) {
    revokePolicy();
    publishEvent("scan_policy_error", "", "lease_expired");
  }
  if (!networkReady() || !buffer_ready_) {
    revokePolicy();
    if (mqtt_.connected()) mqtt_.disconnect();
    return;
  }

  if (!mqtt_.connected()) {
    revokePolicy();  // reconnect never reuses an old policy or command
    if (now - last_mqtt_attempt_ms_ < 5000) return;
    last_mqtt_attempt_ms_ = now;

    char will_topic[48];
    snprintf(will_topic, sizeof will_topic, "%s/status", base_);
    const char* will_msg = "{\"online\":false}";
    net_.guard.reset();
    const bool ok = mqtt_.connect(cfg_.gw_id, nullptr, nullptr, will_topic, 1,
                                  true, will_msg);
    if (ok) {
      Serial.printf("[mqtt] connected to %s:%u\n", cfg_.mqtt_host,
                    (unsigned)cfg_.mqtt_port);
      char cmd_topic[48];
      snprintf(cmd_topic, sizeof cmd_topic, "%s/cmd", base_);
      mqtt_.subscribe(cmd_topic);
      char policy_topic[64];
      snprintf(policy_topic, sizeof policy_topic, "%s/scan-policy", base_);
      if (!mqtt_.subscribe(policy_topic)) publishEvent("scan_policy_error", "", "subscribe_failed");
      status_pending_ = true;  // discover gateway before waiting for the first policy
      flushQueue();
    }
    return;
  }

  mqtt_.loop();
  if (net_.guard.takeError()) {
    revokePolicy();
    publishEvent("scan_policy_error", "", "mqtt_packet_oversize_or_malformed");
  }
  if (!mqtt_.connected()) revokePolicy();
}

void MqttLink::revokePolicy() {
  cancelPendingCommand("policy_revoked");
  rejectPendingManualMeasure("policy_revoked");
  if (!policy_installed_) return;
  policy_installed_ = false;
  policy_.revoke();
  ble_->stopScanPolicy();
  schedule_->sync(policy_, millis());
  status_pending_ = true;
}

void MqttLink::receivePolicy(const uint8_t* payload, size_t len) {
  const uint32_t received = millis();
  if (!policy_.ready(received)) revokePolicy();
  const char* error = nullptr;
  if (!roztash::parseScanPolicy(reinterpret_cast<const char*>(payload), len, incoming_policy_, error)) {
    revokePolicy();
    publishEvent("scan_policy_error", "", error);
    return;
  }
  const auto& old = policy_.policy();
  const bool changed = !policy_.ready(received) || old.active_count != incoming_policy_.active_count ||
      old.health_count != incoming_policy_.health_count ||
      old.emergency_count != incoming_policy_.emergency_count ||
      old.health_interval_s != incoming_policy_.health_interval_s ||
      memcmp(old.active.data(), incoming_policy_.active.data(), incoming_policy_.active_count * sizeof(roztash::PolicyMac)) ||
      memcmp(old.health.data(), incoming_policy_.health.data(), incoming_policy_.health_count * sizeof(roztash::PolicyMac)) ||
      memcmp(old.emergency.data(), incoming_policy_.emergency.data(), incoming_policy_.emergency_count * sizeof(roztash::PolicyMac));
  policy_.apply(incoming_policy_, received);
  policy_installed_ = true;
  ble_->setScanPolicy(incoming_policy_, received);
  schedule_->sync(policy_, received);  // removes revoked entries without resetting progress
  const auto* pending = vibration_commands_.pending();
  if (pending && (pending->emergency ? !policy_.allowsEmergency(pending->mac, received)
                                     : !policy_.allows(pending->mac, received)))
    cancelPendingCommand("policy_revoked");
  const auto* manual = manual_measurements_.pendingCommand();
  if (manual && !policy_.allowsHealth(manual->mac, received))
    rejectPendingManualMeasure("policy_revoked");
  if (changed) status_pending_ = true;
  flushQueue();
}

// Consume-once read of the last received command (callback-set).
bool MqttLink::takeCommand(char* action, size_t action_cap, char* mac,
                           size_t mac_cap, bool* emergency, uint8_t* repeats,
                           uint8_t* completed_pulses) {
  roztash::VibrationCommand command;
  const auto result = vibration_commands_.take(millis(), command);
  if (result == roztash::CommandTake::None) return false;
  if (result == roztash::CommandTake::Expired) {
    publishCommandEvent("cmd_reject", command, "command_expired");
    return false;
  }
  if (command.emergency ? !policy_.allowsEmergency(command.mac, millis())
                        : !policy_.allows(command.mac, millis())) {
    rejectVibration("policy_revoked");
    return false;
  }
  strlcpy(action, "vibrate", action_cap);
  strlcpy(mac, command.mac, mac_cap);
  if (emergency) *emergency = command.emergency;
  if (repeats) *repeats = command.repeats;
  if (completed_pulses) *completed_pulses = command.completed_pulses;
  return true;
}

bool MqttLink::takeManualMeasure(char* mac, size_t mac_cap, bool* vitals,
                                 char* request_id, size_t request_id_cap) {
  roztash::ManualMeasureCommand command;
  const auto result = manual_measurements_.take(millis(), command);
  if (result == roztash::ManualMeasureTake::None) return false;
  if (result == roztash::ManualMeasureTake::Expired) {
    publishManualEvent("measure_reject", command, "command_expired");
    return false;
  }
  if (!policy_.allowsHealth(command.mac, millis()) ||
      !ble_->hasFreshSighting(command.mac, millis())) {
    publishManualEvent("measure_reject", command, "off_duty_unseen_or_policy");
    manual_measurements_.cancelActive(command);
    return false;
  }
  strlcpy(mac, command.mac, mac_cap);
  strlcpy(request_id, command.request_id, request_id_cap);
  if (vitals) *vitals = command.vitals;
  return true;
}

void MqttLink::manualMeasureStarted() {
  const auto* command = manual_measurements_.activeCommand();
  if (command) publishManualEvent("measure_started", *command, "");
}

void MqttLink::finishManualMeasure(const char* type, const char* detail) {
  const auto* command = manual_measurements_.activeCommand();
  if (!command) return;
  const roztash::ManualMeasureCommand result = *command;
  publishManualEvent(type, result, detail);
  manual_measurements_.finish(millis());
}

void MqttLink::rejectPendingManualMeasure(const char* detail) {
  roztash::ManualMeasureCommand command;
  if (manual_measurements_.cancelPending(command))
    publishManualEvent("measure_reject", command, detail);
}

void MqttLink::publishCommandEvent(const char* type, const roztash::VibrationCommand& command,
                                  const char* detail) {
  JsonDocument doc;
  doc["gw"] = cfg_.gw_id;
  doc["type"] = type;
  doc["mac"] = command.mac;
  if (command.tracked()) {
    doc["request_id"] = command.request_id;
    doc["reason"] = command.reason;
    doc["repeats"] = command.repeats;
    doc["completed_pulses"] = command.completed_pulses;
  }
  if (detail && detail[0]) doc["detail"] = detail;
  String output;
  serializeJson(doc, output);
  char topic[48];
  snprintf(topic, sizeof topic, "%s/event", base_);
  send(topic, output.c_str(), false, true);
}

void MqttLink::publishManualEvent(const char* type,
                                  const roztash::ManualMeasureCommand& command,
                                  const char* detail) {
  JsonDocument doc;
  doc["gw"] = cfg_.gw_id;
  doc["type"] = type;
  doc["reason"] = "manual_measure";
  doc["request_id"] = command.request_id;
  doc["mac"] = command.mac;
  if (detail && detail[0]) doc["detail"] = detail;
  String output;
  serializeJson(doc, output);
  char topic[48];
  snprintf(topic, sizeof topic, "%s/event", base_);
  send(topic, output.c_str(), false, true);
}

void MqttLink::cancelPendingCommand(const char* detail) {
  roztash::VibrationCommand command;
  if (vibration_commands_.cancelPending(command)) publishCommandEvent("cmd_reject", command, detail);
}

void MqttLink::finishVibration(bool success, uint8_t completed_pulses, const char* detail) {
  const auto* command = vibration_commands_.active();
  if (!command) return;
  roztash::VibrationCommand result = *command;
  result.completed_pulses = completed_pulses;
  publishCommandEvent(success ? "vibrated" : "vibrate_fail", result, detail);
  vibration_commands_.finish(success, millis(), completed_pulses);
}

void MqttLink::rejectVibration(const char* detail, uint8_t completed_pulses) {
  const auto* command = vibration_commands_.active();
  if (!command) return;
  roztash::VibrationCommand result = *command;
  if (completed_pulses > result.completed_pulses) result.completed_pulses = completed_pulses;
  publishCommandEvent("cmd_reject", result, detail);
  vibration_commands_.finish(false, millis(), result.completed_pulses);
}

// --- publishing -------------------------------------------------------------
bool MqttLink::send(const char* topic, const char* payload, bool retained,
                    bool queue_if_offline) {
  if (mqtt_.connected() && mqtt_.publish(topic, payload, retained)) return true;
  return queue_if_offline && queueLine(topic, payload);
}

void MqttLink::publishStatus(const char* fw, const char* ip,
                             int bands_seen, uint32_t adv_seen) {
  JsonDocument doc;
  doc["gw"] = cfg_.gw_id;
  doc["zone"] = cfg_.zone;
  doc["fw"] = fw;
  doc["online"] = true;
  doc["ip"] = ip;
  doc["transport"] = "ethernet";
  doc["uptime_s"] = (uint32_t)(millis() / 1000UL);
  doc["bands_seen"] = bands_seen;
  doc["adv_seen"] = adv_seen;  // permitted advertisements only
  const bool scan_policy_ready = policy_.ready(millis()) && ble_->policyReady();
  doc["scan_policy_ready"] = scan_policy_ready;
  doc["scan_enabled"] = ble_->scanEnabled();
  doc["scan_reason"] = !scan_policy_ready ? "policy_unavailable_or_expired"
      : (policy_.policy().active_count == 0 && policy_.policy().emergency_count == 0
          ? "no_active_or_emergency_macs" : "policy_allows_scan");
  doc["health_schedule_enabled"] = scan_policy_ready && policy_.policy().health_count > 0;
  doc["active_count"] = policy_.policy().active_count;
  doc["health_count"] = policy_.policy().health_count;
  doc["emergency_count"] = policy_.policy().emergency_count;
  doc["manual_measurement"] = true;
  doc["manual_measure_pending"] = manual_measurements_.pending();
  doc["manual_measure_active"] = manual_measurements_.active();
  doc["health_interval_s"] = policy_.policy().health_interval_s;
  doc["health_job_active"] = ble_->healthBusy();
  doc["vibration_request_id"] = true;
  doc["vibration_repeats"] = 3;
  String out;
  serializeJson(doc, out);
  char topic[48];
  snprintf(topic, sizeof topic, "%s/status", base_);
  send(topic, out.c_str(), true, false);
}

void MqttLink::publishPresence(BleCentral& ble) {
  JsonDocument doc;
  doc["gw"] = cfg_.gw_id;
  doc["ts"] = (uint32_t)(millis() / 1000UL);
  JsonArray arr = doc["bands"].to<JsonArray>();
  int count = 0;
  if (ble.healthBusy() && policy_.allows(ble.jobMac(), millis())) {
    doc["connected_mac"] = ble.jobMac();
    doc["advertising_gap"] = true;  // this band's location may be stale while connected
  }
  for (int i = 0; i < BleCentral::kMaxBands; ++i) {
    BleCentral::Sighting s;
    if (!ble.getSlot(i, s) || !s.used ||
        (!policy_.allows(s.mac, millis()) && !policy_.allowsEmergency(s.mac, millis()))) continue;
    const uint32_t age = uint32_t(millis() - s.seen_ms);
    if (age > roztash::kSightingFreshMs) continue;
    ++count;
    JsonObject o = arr.add<JsonObject>();
    o["mac"] = s.mac;
    o["rssi"] = s.rssi;
    o["age_ms"] = age;
  }
  doc["n"] = count;
  String out;
  serializeJson(doc, out);
  char topic[48];
  snprintf(topic, sizeof topic, "%s/presence", base_);
  send(topic, out.c_str(), false, false);  // presence is stale quickly: no queue
}

bool MqttLink::publishHealth(const BleCentral& ble) {
  if (!policy_.allowsHealth(ble.jobMac(), millis()) || ble.jobRevoked()) return false;
  JsonDocument doc;
  doc["gw"] = cfg_.gw_id;
  doc["mac"] = ble.jobMac();
  if (ble.wasManualMeasure()) doc["request_id"] = ble.manualRequestId();
  doc["state"] = ble.state() == BleCentral::JobState::Done ? "done" : "failed";
  doc["fail"] = failName(ble.failure());
  doc["wearing"] = ble.wearingOk();
  doc["ended"] = ble.ended();
  const uint8_t n = ble.sampleCount();
  const uint8_t* s = ble.samples();
  JsonArray bpm = doc["bpm"].to<JsonArray>();
  uint32_t sum = 0;
  for (uint8_t i = 0; i < n; ++i) {
    bpm.add(s[i]);
    sum += s[i];
  }
  doc["n"] = n;
  doc["avg"] = n ? (float)sum / n : 0;
  String out;
  serializeJson(doc, out);
  char topic[48];
  snprintf(topic, sizeof topic, "%s/health", base_);
  const bool published = send(topic, out.c_str(), false, true);  // queue health when offline
  Serial.printf("[mqtt] health -> %s\n", out.c_str());
  return published;
}

// "C1C2:PAYLOAD" — one compact hex line per captured raw frame.
static void rawToHex(const BleCentral::RawFrame& f, char* out, size_t cap) {
  snprintf(out, cap, "%02X%02X:", f.c1, f.c2);
  size_t off = strlen(out);
  for (uint8_t i = 0; i < f.len && (off + 3) <= cap; ++i)
    off += snprintf(out + off, cap - off, "%02X", f.data[i]);
}

void MqttLink::publishVitals(const BleCentral& ble) {
  if (!policy_.allowsHealth(ble.jobMac(), millis()) || ble.jobRevoked()) return;
  const BleCentral::Vitals& v = ble.vitals();
  JsonDocument doc;
  doc["gw"] = cfg_.gw_id;
  doc["mac"] = ble.jobMac();
  if (ble.wasManualMeasure()) doc["request_id"] = ble.manualRequestId();
  if (v.battery_ok) doc["battery"] = v.battery;
  if (v.dev_fw[0]) doc["dev_fw"] = v.dev_fw;
  if (v.dev_hw[0]) doc["dev_hw"] = v.dev_hw;
  if (v.dev_maker[0]) doc["dev_maker"] = v.dev_maker;
  doc["spo2_ack"] = v.spo2_ack;
  doc["hrv_ack"] = v.hrv_ack;
  if (v.steps_ok) doc["steps"] = v.steps;
  JsonArray spo2 = doc["spo2_raw"].to<JsonArray>();
  for (uint8_t i = 0; i < v.spo2_frames; ++i) {
    char hex[3 * BleCentral::kMaxRawLen + 4];
    rawToHex(v.spo2[i], hex, sizeof hex);
    spo2.add(hex);
  }
  JsonArray hrv = doc["hrv_raw"].to<JsonArray>();
  for (uint8_t i = 0; i < v.hrv_frames; ++i) {
    char hex[3 * BleCentral::kMaxRawLen + 4];
    rawToHex(v.hrv[i], hex, sizeof hex);
    hrv.add(hex);
  }
  String out;
  serializeJson(doc, out);
  char topic[48];
  snprintf(topic, sizeof topic, "%s/vitals", base_);
  send(topic, out.c_str(), false, true);  // queue vitals when offline
  Serial.printf("[mqtt] vitals -> %s\n", out.c_str());
}

void MqttLink::publishEvent(const char* type, const char* mac,
                            const char* detail) {
  JsonDocument doc;
  doc["gw"] = cfg_.gw_id;
  doc["type"] = type;
  doc["mac"] = mac;
  if (detail && detail[0]) doc["detail"] = detail;
  String out;
  serializeJson(doc, out);
  char topic[48];
  snprintf(topic, sizeof topic, "%s/event", base_);
  send(topic, out.c_str(), false, true);
}

// --- offline queue ----------------------------------------------------------
bool MqttLink::queueLine(const char* topic, const char* payload) {
  // topic carries the base prefix; store only the suffix + payload as JSONL
  const char* suffix = topic + strlen(base_);
  File f = LittleFS.open(kQueuePath, "a");
  if (!f) return false;
  if ((size_t)f.size() > kQueueMaxBytes) {
    f.close();
    LittleFS.remove(kQueuePath);  // drop the whole backlog rather than grow
    f = LittleFS.open(kQueuePath, "a");
    if (!f) return false;
  }
  f.printf("{\"t\":\"%s\",\"p\":%s}\n", suffix, payload);
  const bool ok = f.getWriteError() == 0;
  f.close();
  return ok;
}

void MqttLink::flushQueue() {
  if (!policy_.ready(millis())) return;  // reconnect has no authority to replay band data
  File f = LittleFS.open(kQueuePath, "r");
  if (!f) return;
  if ((size_t)f.size() > kQueueMaxBytes) {
    f.close();
    LittleFS.remove(kQueuePath);
    return;
  }
  while (f.available()) {
    String line = f.readStringUntil('\n');
    if (line.isEmpty()) continue;
    JsonDocument doc;
    if (deserializeJson(doc, line)) continue;
    const char* mac = doc["p"]["mac"] | "";
    if (mac[0] && !policy_.allows(mac, millis())) continue;
    if (!mqtt_.connected()) break;
    char topic[48];
    snprintf(topic, sizeof topic, "%s%s", base_, (const char*)(doc["t"] | ""));
    doc["p"]["replayed"] = true;  // bridge must not label queued readings as current
    String payload;
    serializeJson(doc["p"], payload);
    mqtt_.publish(topic, payload.c_str());
  }
  f.close();
  LittleFS.remove(kQueuePath);
  Serial.println("[mqtt] offline queue flushed");
}
