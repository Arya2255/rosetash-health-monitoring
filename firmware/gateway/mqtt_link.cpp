#include "mqtt_link.h"

#include <ArduinoJson.h>
#include <LittleFS.h>

static const char* kQueuePath = "/queue.jsonl";
static const size_t kQueueMaxBytes = 32 * 1024;  // drop oldest wholesale when full

static const char* failName(BleCentral::Fail f) {
  switch (f) {
    case BleCentral::Fail::None: return "none";
    case BleCentral::Fail::Connect: return "connect";
    case BleCentral::Fail::Subscribe: return "subscribe";
    case BleCentral::Fail::Write: return "write";
    case BleCentral::Fail::Timeout: return "timeout";
  }
  return "?";
}

void MqttLink::begin(const GatewayConfig& cfg) {
  cfg_ = cfg;
  snprintf(base_, sizeof base_, "roztash/%s", cfg_.gw_id);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  if (strlen(cfg_.wifi_ssid)) WiFi.begin(cfg_.wifi_ssid, cfg_.wifi_pass);

  mqtt_.setServer(cfg_.mqtt_host, cfg_.mqtt_port);
  mqtt_.setBufferSize(2048);  // presence batches can exceed the default 256

  // Remote commands (roztash/<gw>/cmd). The callback runs inside mqtt_.loop()
  // (single task) — parsing here and handing over via takeCommand() is safe.
  mqtt_.setCallback([this](char* topic, uint8_t* payload, unsigned int len) {
    JsonDocument doc;
    if (deserializeJson(doc, payload, len)) return;
    const char* action = doc["action"] | "";
    if (!action[0]) return;
    strlcpy(cmd_action_, action, sizeof cmd_action_);
    strlcpy(cmd_mac_, doc["mac"] | "", sizeof cmd_mac_);
    cmd_pending_ = true;
    Serial.printf("[mqtt] command received: %s %s\n", cmd_action_, cmd_mac_);
  });
}

// --- connection maintenance -------------------------------------------------
void MqttLink::poll() {
  const uint32_t now = millis();

  if (WiFi.status() != WL_CONNECTED) {
    if (now - last_wifi_attempt_ms_ > 10000) {
      last_wifi_attempt_ms_ = now;
      WiFi.reconnect();
    }
    return;
  }

  if (!mqtt_.connected()) {
    if (now - last_mqtt_attempt_ms_ < 5000) return;
    last_mqtt_attempt_ms_ = now;

    char will_topic[48];
    snprintf(will_topic, sizeof will_topic, "%s/status", base_);
    const char* will_msg = "{\"online\":false}";
    const bool ok = mqtt_.connect(cfg_.gw_id, nullptr, nullptr, will_topic, 1,
                                  true, will_msg);
    if (ok) {
      Serial.printf("[mqtt] connected to %s:%u\n", cfg_.mqtt_host,
                    (unsigned)cfg_.mqtt_port);
      char cmd_topic[48];
      snprintf(cmd_topic, sizeof cmd_topic, "%s/cmd", base_);
      mqtt_.subscribe(cmd_topic);
      flushQueue();
    }
    return;
  }

  mqtt_.loop();
}

// Consume-once read of the last received command (callback-set).
bool MqttLink::takeCommand(char* action, size_t action_cap, char* mac,
                           size_t mac_cap) {
  if (!cmd_pending_) return false;
  cmd_pending_ = false;
  strlcpy(action, cmd_action_, action_cap);
  strlcpy(mac, cmd_mac_, mac_cap);
  return true;
}

// --- publishing -------------------------------------------------------------
bool MqttLink::send(const char* topic, const char* payload, bool retained,
                    bool queue_if_offline) {
  if (mqtt_.connected() && mqtt_.publish(topic, payload, retained)) return true;
  if (queue_if_offline) queueLine(topic, payload);
  return false;
}

void MqttLink::publishStatus(const char* fw, int wifi_rssi, const char* ip,
                             int bands_seen, uint32_t adv_seen) {
  JsonDocument doc;
  doc["gw"] = cfg_.gw_id;
  doc["zone"] = cfg_.zone;
  doc["fw"] = fw;
  doc["online"] = true;
  doc["ip"] = ip;
  doc["rssi"] = wifi_rssi;
  doc["uptime_s"] = (uint32_t)(millis() / 1000UL);
  doc["bands_seen"] = bands_seen;
  doc["adv_seen"] = adv_seen;  // total adv packets since boot (radio liveness)
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
  const int count = ble.sightingCount();
  for (int i = 0; i < BleCentral::kMaxBands; ++i) {
    BleCentral::Sighting s;
    if (!ble.getSlot(i, s) || !s.used) continue;
    JsonObject o = arr.add<JsonObject>();
    o["mac"] = s.mac;
    o["rssi"] = s.rssi;
  }
  doc["n"] = count;
  String out;
  serializeJson(doc, out);
  char topic[48];
  snprintf(topic, sizeof topic, "%s/presence", base_);
  send(topic, out.c_str(), false, false);  // presence is stale quickly: no queue
}

void MqttLink::publishHealth(const BleCentral& ble) {
  JsonDocument doc;
  doc["gw"] = cfg_.gw_id;
  doc["mac"] = ble.jobMac();
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
  send(topic, out.c_str(), false, true);  // queue health when offline
  Serial.printf("[mqtt] health -> %s\n", out.c_str());
}

// "C1C2:PAYLOAD" — one compact hex line per captured raw frame.
static void rawToHex(const BleCentral::RawFrame& f, char* out, size_t cap) {
  snprintf(out, cap, "%02X%02X:", f.c1, f.c2);
  size_t off = strlen(out);
  for (uint8_t i = 0; i < f.len && (off + 3) <= cap; ++i)
    off += snprintf(out + off, cap - off, "%02X", f.data[i]);
}

void MqttLink::publishVitals(const BleCentral& ble) {
  const BleCentral::Vitals& v = ble.vitals();
  JsonDocument doc;
  doc["gw"] = cfg_.gw_id;
  doc["mac"] = ble.jobMac();
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
void MqttLink::queueLine(const char* topic, const char* payload) {
  // topic carries the base prefix; store only the suffix + payload as JSONL
  const char* suffix = topic + strlen(base_);
  File f = LittleFS.open(kQueuePath, "a");
  if (!f) return;
  if ((size_t)f.size() > kQueueMaxBytes) {
    f.close();
    LittleFS.remove(kQueuePath);  // drop the whole backlog rather than grow
    f = LittleFS.open(kQueuePath, "a");
    if (!f) return;
  }
  f.printf("{\"t\":\"%s\",\"p\":%s}\n", suffix, payload);
  f.close();
}

void MqttLink::flushQueue() {
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
    if (!mqtt_.connected()) break;
    char topic[48];
    snprintf(topic, sizeof topic, "%s%s", base_, (const char*)(doc["t"] | ""));
    String payload;
    serializeJson(doc["p"], payload);
    mqtt_.publish(topic, payload.c_str());
  }
  f.close();
  LittleFS.remove(kQueuePath);
  Serial.println("[mqtt] offline queue flushed");
}
