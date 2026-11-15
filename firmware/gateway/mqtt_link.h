// gateway/mqtt_link.h — Ethernet + MQTT publishing with an offline queue.
//
// Topics (prefix = roztash/<gw_id>):
//   /status     retained heartbeat + LWT offline marker
//   /presence   periodic batch of {mac, rssi} sightings (10 s)
//   /health     finished measurement: {mac, bpm[], n, avg, wearing, ended, state}
//   /vitals     battery percent, device info and raw SpO2/HRV frames (same job)
//   /event      errors worth surfacing: wearing_error, connect_fail, ...
//   /cmd        SUBSCRIBED — remote commands: {"action":"vibrate","mac":"..."}
#pragma once

#include <Arduino.h>
#include <PubSubClient.h>
#include <Network.h>

#include "ble_central.h"
#include "config.h"
#include "network_config.h"

class MqttLink {
 public:
  void begin(const GatewayConfig& cfg);  // starts W5500 Ethernet with DHCP
  void setBroker(const char* host, uint16_t port);
  void poll();  // Ethernet/MQTT reconnect + queue flush; call every loop()
  bool online() { return mqtt_.connected(); }
  bool networkReady() const;

  void publishStatus(const char* fw, const char* ip,
                     int bands_seen, uint32_t adv_seen);
  void publishPresence(BleCentral& ble);
  void publishHealth(const BleCentral& ble);
  void publishVitals(const BleCentral& ble);
  void publishEvent(const char* type, const char* mac, const char* detail);

  // Remote commands from roztash/<gw>/cmd — consume-once.
  bool takeCommand(char* action, size_t action_cap, char* mac, size_t mac_cap);

 private:
  bool send(const char* topic, const char* payload, bool retained,
            bool queue_if_offline);
  void queueLine(const char* topic, const char* payload);
  void flushQueue();

  NetworkClient net_;
  PubSubClient mqtt_{net_};
  GatewayConfig cfg_{};
  char base_[40] = {0};
  uint32_t last_mqtt_attempt_ms_ = 0;
  char cmd_action_[16] = {0};
  char cmd_mac_[20] = {0};
  volatile bool cmd_pending_ = false;
};
