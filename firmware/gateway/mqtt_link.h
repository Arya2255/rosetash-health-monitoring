// gateway/mqtt_link.h — WiFi + MQTT publishing with a simple offline queue.
//
// Topics (prefix = roztash/<gw_id>):
//   /status     retained heartbeat + LWT offline marker
//   /presence   periodic batch of {mac, rssi} sightings (10 s)
//   /health     finished measurement: {mac, bpm[], n, avg, wearing, ended, state}
//   /event      errors worth surfacing: wearing_error, connect_fail, ...
#pragma once

#include <Arduino.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include "ble_central.h"
#include "config.h"

class MqttLink {
 public:
  void begin(const GatewayConfig& cfg);
  void poll();  // wifi/mqtt reconnect + queue flush; call every loop()
  bool online() { return mqtt_.connected(); }

  void publishStatus(const char* fw, int wifi_rssi, const char* ip);
  void publishPresence(BleCentral& ble);
  void publishHealth(const BleCentral& ble);
  void publishEvent(const char* type, const char* mac, const char* detail);

 private:
  bool send(const char* topic, const char* payload, bool retained,
            bool queue_if_offline);
  void queueLine(const char* topic, const char* payload);
  void flushQueue();

  WiFiClient net_;
  PubSubClient mqtt_{net_};
  GatewayConfig cfg_{};
  char base_[40] = {0};
  uint32_t last_wifi_attempt_ms_ = 0;
  uint32_t last_mqtt_attempt_ms_ = 0;
};
